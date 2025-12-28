import os
import json
import time
import shutil
import hashlib
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from cloudexport.config import settings
from cloudexport.database import SessionLocal, init_db
from cloudexport.models import Job, JobEvent, Usage, CacheEntry
from cloudexport.queue import dequeue_job, publish_progress
from cloudexport.storage import download_file, upload_file, generate_presigned_get
from cloudexport.compatibility import check_manifest
from cloudexport.emailer import send_email
from cloudexport.utils import current_month
from cloudexport.credits import settle_job_credits, void_reservation
from cloudexport.pricing import compute_actual_cost

STATUS_PROGRESS = {
    'DOWNLOADING': 10,
    'VALIDATING': 20,
    'RENDERING': 60,
    'PACKAGING': 85,
    'UPLOADING': 92,
    'COMPLETED': 100,
    'FAILED': 0,
    'CANCELLED': 0
}


def compute_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def update_job(db: Session, job: Job, status: str, message: str, progress: float | None = None, error: str | None = None):
    job.status = status
    if progress is None:
        progress = STATUS_PROGRESS.get(status, job.progress_percent)
    job.progress_percent = progress
    if status == 'RENDERING' and job.started_at is None:
        job.started_at = datetime.utcnow()
    if status in {'COMPLETED', 'FAILED', 'CANCELLED'}:
        job.finished_at = datetime.utcnow()
    if error:
        job.error_message = error
    db.add(JobEvent(job_id=job.id, event_type=status, message=message))
    db.commit()
    publish_progress(job.id, {
        'jobId': job.id,
        'status': job.status,
        'progressPercent': job.progress_percent,
        'errorMessage': job.error_message
    })


def update_usage(db: Session, job: Job, minutes: float):
    month = current_month()
    usage = db.query(Usage).filter(Usage.user_id == job.user_id, Usage.month == month).one_or_none()
    if not usage:
        usage = Usage(user_id=job.user_id, month=month, cost_usd=0.0, minutes=0.0)
    usage.cost_usd += job.cost_final_usd or 0.0
    usage.minutes += minutes
    usage.updated_at = datetime.utcnow()
    db.add(usage)
    db.commit()


def build_render_command(project_path: str, comp_name: str, output_path: str) -> list[str]:
    aerender = os.environ.get('AERENDER_PATH', 'aerender')
    return [
        aerender,
        '-project', project_path,
        '-comp', comp_name,
        '-output', output_path,
        '-continueOnMissingFootage'
    ]


def run_render(command: list[str], job: Job, db: Session):
    start_time = time.time()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while True:
        line = process.stdout.readline()
        if line:
            if 'PROGRESS:' in line:
                try:
                    percent = float(line.split('PROGRESS:')[-1].strip().replace('%', ''))
                    update_job(db, job, 'RENDERING', 'Rendering', progress=min(90, 30 + percent * 0.6))
                except ValueError:
                    pass
        if process.poll() is not None:
            break
        db.refresh(job)
        if job.cancel_requested:
            process.terminate()
            update_job(db, job, 'CANCELLED', 'Render cancelled by user')
            raise RuntimeError('cancelled')
        if (time.time() - start_time) > settings.render_timeout_minutes * 60:
            process.terminate()
            update_job(db, job, 'FAILED', 'Render timed out', error='Render timeout')
            raise RuntimeError('timeout')
    if process.returncode != 0:
        raise RuntimeError('aerender failed')


def transcode_output(input_path: str, preset: str, custom_options: dict | None, output_dir: Path, output_name: str) -> str:
    output_path = output_dir / output_name
    if preset == 'high_quality':
        output_path = output_path.with_suffix('.mov')
        cmd = [
            'ffmpeg', '-y', '-i', str(input_path),
            '-c:v', 'prores_ks', '-profile:v', '3',
            '-c:a', 'pcm_s16le',
            str(output_path)
        ]
    else:
        codec = 'h264'
        bitrate = 8
        if preset == 'social':
            bitrate = 12
        if preset == 'custom' and custom_options:
            bitrate = float(custom_options.get('bitrateMbps', bitrate))
            codec = custom_options.get('codec', codec)
        if codec == 'prores':
            output_path = output_path.with_suffix('.mov')
            cmd = [
                'ffmpeg', '-y', '-i', str(input_path),
                '-c:v', 'prores_ks', '-profile:v', '3',
                '-c:a', 'pcm_s16le',
                str(output_path)
            ]
        else:
            output_path = output_path.with_suffix('.mp4')
            cmd = [
                'ffmpeg', '-y', '-i', str(input_path),
                '-c:v', 'libx264', '-preset', 'fast',
                '-b:v', f'{bitrate}M',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                str(output_path)
            ]
    subprocess.check_call(cmd)
    return str(output_path)


def process_job(job_id: str):
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).one_or_none()
    if not job:
        db.close()
        return
    try:
        update_job(db, job, 'DOWNLOADING', 'Downloading bundle')
        work_dir = Path('/tmp') / f'cloudexport-{job.id}'
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        bundle_path = work_dir / 'bundle.zip'
        download_file(job.bundle_key, str(bundle_path))
        if job.bundle_sha256 not in ('pending', 'cache'):
            digest = compute_sha256(str(bundle_path))
            if digest != job.bundle_sha256:
                raise RuntimeError('Bundle checksum mismatch')

        update_job(db, job, 'VALIDATING', 'Validating bundle')
        with zipfile.ZipFile(bundle_path, 'r') as zip_ref:
            zip_ref.extractall(work_dir)

        manifest_path = work_dir / 'manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('Manifest missing from bundle')
        manifest = json.loads(manifest_path.read_text())
        warnings, errors = check_manifest(manifest)
        if errors:
            raise RuntimeError('; '.join(errors))

        project_path = work_dir / 'project.aep'
        if not project_path.exists():
            raise RuntimeError('Project file missing in bundle')

        output_dir = work_dir / 'output'
        output_dir.mkdir(exist_ok=True)
        intermediate_path = output_dir / 'render.mov'

        update_job(db, job, 'RENDERING', 'Rendering')
        command = build_render_command(str(project_path), manifest['composition']['name'], str(intermediate_path))
        run_render(command, job, db)

        update_job(db, job, 'PACKAGING', 'Transcoding')
        output_path = transcode_output(
            str(intermediate_path),
            job.preset,
            job.custom_options,
            output_dir,
            job.output_name
        )
        job.output_name = Path(output_path).name

        update_job(db, job, 'UPLOADING', 'Uploading render')
        result_key = f'results/{job.user_id}/{job.id}/{Path(output_path).name}'
        upload_file(output_path, result_key)

        minutes = max(1.0, (datetime.utcnow() - (job.started_at or datetime.utcnow())).total_seconds() / 60.0)
        actual_cost = compute_actual_cost(
            job.manifest,
            job.preset,
            job.bundle_size_bytes,
            minutes,
            job.custom_options
        )
        job.result_key = result_key
        job.cost_final_usd = actual_cost
        update_job(db, job, 'COMPLETED', 'Completed', progress=100.0)
        settle_job_credits(db, job.id, actual_cost)
        update_usage(db, job, minutes)

        cache = CacheEntry(
            manifest_hash=job.manifest_hash,
            preset=job.preset,
            result_key=result_key,
            output_name=Path(output_path).name
        )
        db.add(cache)
        db.commit()

        if job.notification_email:
            download_url = generate_presigned_get(result_key)
            send_email(
                job.notification_email,
                'CloudExport render complete',
                f'Your render is ready: {download_url}'
            )
    except RuntimeError as err:
        if str(err) == 'cancelled':
            void_reservation(db, job.id, 'cancelled')
            db.close()
            return
        job.attempts += 1
        if job.attempts < job.max_attempts:
            update_job(db, job, 'QUEUED', f'Retrying ({job.attempts})', progress=10)
            enqueue = os.environ.get('GPU_CLASS', job.gpu_class)
            from cloudexport.queue import enqueue_job
            enqueue_job(job.id, enqueue)
        else:
            update_job(db, job, 'FAILED', 'Render failed', error=str(err))
            void_reservation(db, job.id, 'failed')
    except Exception as err:
        update_job(db, job, 'FAILED', 'Unhandled error', error=str(err))
        void_reservation(db, job.id, 'failed')
    finally:
        db.close()
        if 'work_dir' in locals() and Path(work_dir).exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def main():
    init_db()
    gpu_class = os.environ.get('GPU_CLASS', 'rtx4090')
    while True:
        job_id = dequeue_job(gpu_class, timeout=5)
        if not job_id:
            continue
        process_job(job_id)


if __name__ == '__main__':
    main()
