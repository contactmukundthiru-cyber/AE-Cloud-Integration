from email.mime.text import MIMEText
import smtplib
from .config import settings


def send_email(to_address: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_user:
        return
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = settings.smtp_from
    msg['To'] = to_address
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password or '')
        server.sendmail(settings.smtp_from, [to_address], msg.as_string())
