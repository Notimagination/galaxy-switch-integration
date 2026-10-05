# GOG Galaxy Nintendo Switch Integration

> **Disclaimer:** This is the first and likely the final version of this plugin. However, I will monitor and address specific issues such as game detection if they arise.

## ✨ Features

* **File Support:** Supports all Nintendo Switch files.

* **Integrated Playtime:** Playtime tracking is directly linked to the GOG system.

* **Emulator Support:** Multiple emulators are supported (Eden has the best compatibility and it's used as default).

## 📦 Installation Guide

1. Download the `.zip` file from this repository, or you can check the [releases](https://github.com/Notimagination/galaxy-switch-integration/releases) page for the latest updates.
   
 <img width="930" height="351" alt="Captura de pantalla 2026-10-04 215901" src="https://github.com/user-attachments/assets/e9b32e34-fd6e-4b3e-8412-d43addc2ae3d" />

2. Extract and move the `SwitchPlugin` folder to your GOG Galaxy plugins directory:

   ```
   %localappdata%\GOG.com\Galaxy\plugins\installed
   ```

3. Open **GOG Galaxy**, go to **Settings** > **Integrations**, and look for **Nintendo Switch**. Click **Connect**.

   <img width="578" height="327" alt="step2" src="https://github.com/user-attachments/assets/9d7c4ac7-bb06-409d-871c-7445d72b90c9" />

4. Configure your paths:

   * Game paths must use backslashes (`\`).

   * Emulator paths must use forward slashes (`/`).

   <img width="598" height="1457" alt="step3" src="https://github.com/user-attachments/assets/40ccbbe1-35bc-4fcd-a249-1351e5c3ac68" />

5. Click the **Save config** button and wait for your games to import.

   <img width="1906" height="870" alt="Captura de pantalla 2026-10-04 214949" src="https://github.com/user-attachments/assets/a7820776-4ed4-4836-8359-5380d8721b7f" />

## 🎮 Requesting Game Additions

If you would like me to add support for a missing game in a future update, please provide the following details:

* **Game Name**
* **Title Number**
* **The log file** generated at `%programdata%\GOG.com\Galaxy` (`plugin-nswitch-fce8dabb-edad-4636-8bdc-09c66f87c4ed.log`)

🎫 **Open a ticket on the [Issues](https://github.com/Notimagination/galaxy-ps2-integration-renew/issues) page**.

If you're having issues, you should check the [PS2 plugin's](https://github.com/Notimagination/galaxy-ps2-integration-renew#-frequently-asked-questions-faq) Q&A. Same questions, same answers.

