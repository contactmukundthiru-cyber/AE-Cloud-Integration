import { Settings } from '../types';

const DEFAULT_SETTINGS: Settings = {
  apiBaseUrl: 'https://api.cloudexport.io',
  apiKey: '',
  outputDirUrl: '',
  notificationEmail: '',
  allowCache: true
};

async function getSettingsFile() {
  const { storage } = require('uxp');
  const fs = storage.localFileSystem;
  const dataFolder = await fs.getDataFolder();
  try {
    return await dataFolder.getEntry('settings.json');
  } catch (err) {
    return await dataFolder.createFile('settings.json', { overwrite: true });
  }
}

export async function loadSettings(): Promise<Settings> {
  try {
    const file = await getSettingsFile();
    const contents = await file.read();
    if (!contents) {
      return { ...DEFAULT_SETTINGS };
    }
    const parsed = JSON.parse(contents);
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch (err) {
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettings(settings: Settings): Promise<void> {
  const file = await getSettingsFile();
  await file.write(JSON.stringify(settings, null, 2));
}
