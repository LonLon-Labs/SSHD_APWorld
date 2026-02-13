# Skyward Sword HD - Archipelago APWorld

An [Archipelago](https://archipelago.gg) multiworld randomizer integration for **The Legend of Zelda: Skyward Sword HD**.

## What is this?

This APWorld allows you to play Skyward Sword HD in a multiworld randomizer with other Archipelago-supported games. Items are shuffled across all players in a cooperative experience where finding items in your world may send them to players in completely different games!

## Features

- **800+ Locations**: All chests, goddess cubes, NPCs, dungeons, minigames, and more
- **200+ Items**: Progression items, equipment, tablets, keys, consumables
- **Full Logic Support**: Ensures you always have items needed to progress
- **40+ Options**: Customize starting items, logic difficulty, item placement
- **Custom Logos**: Replace title screen with Archipelago branding
- **Cross-Platform**: Works on Windows, Linux, and macOS (maybe, I don't have a mac nor do I use Linux)

## Download

### Pre-built Release
Download the latest `sshd.apworld`, `Skyward Sword HD.yaml`, `launch_sshd.bat` (if using Windows), and `launch_sshd_wrapper.py` files from the [Releases](https://github.com/LonLon-Labs/SSHD_APWorld/releases) page.

### Build from Source
```bash
git clone https://github.com/LonLon-Labs/SSHD_APWorld.git
cd sshd_apworld
python build_apworld.py
```

## System Requirements
- **Archipelago**: Version 0.5.0 or higher (Tested with 0.6.6)
- **Python**: 3.10 or higher (Tested with Python 3.13.9)
- **Emulator**: Ryujinx (Tested on 1.1.1376)
- **Game**: The Legend of Zelda: Skyward Sword HD and Update Data (Switch)

## Quick Start

### 0. Install Python and dependencies

- Install Python 3.10 or higher (MAKE SURE TO ADD IT TO PATH)
- Download and install the dependencies from [requirements.txt](requirements.txt) using either `pip install -r requirements.txt` or if that doesn't work `pip install --target="C:\ProgramData\Archipelago\lib" -r requirements.txt` (change the target path if necessary)

### 1. Install the APWorld and other files

The APWorld will auto-deploy to the correct location for your OS (if building manually):
- **Windows**: `C:\ProgramData\Archipelago\custom_worlds\`
- **Linux**: `~/.local/share/Archipelago/custom_worlds/`
- **macOS**: `~/Library/Application Support/Archipelago/custom_worlds/`

Or manually place `sshd.apworld` in your platform's custom_worlds folder if running from the release.

Place `launch_sshd_wrapper.py` in the Archipelago folder

If using Windows: Place `launch_sshd.bat` in in the Archipelago folder (or somewhere else - it works from anywhere)

### 2. Extract Your Game

You'll need a legally obtained copy of Skyward Sword HD for Nintendo Switch along with the update data.

1. Extract the RomFS and ExeFS from your game using Ryujinx (MAKE SURE THE UPDATE IS INSTALLED BEFORE EXTRACTING)
2. Extract them to your platform's default location:
   - **Windows**: `C:\ProgramData\Archipelago\sshd_extract\`
   - **Linux**: `~/.local/share/Archipelago/sshd_extract/`
   - **macOS**: `~/Library/Application Support/Archipelago/sshd_extract/`
3. Create `romfs/` and `exefs/` subdirectories with your extracted files

### 3. Generate Your Seed

1. Download the [Skyward Sword HD Randomizer](https://github.com/mint-choc-chip-skyblade/sshd-rando/releases/latest)
2. Configure all of your options (don't generate)
3. Open SkywardSwordHD.yaml for use as a template
4. Use Method 1 and input the path to your `config.yaml` file (in the SSHD Rando folder)
5. Put it in `C:\ProgramData\Archipelago\Players`
6. Generate locally using all player yamls
    - Open the Archipelago Launcher and click 'Generate'
    - The outputed file should be in `C:\ProgramData\Archipelago\output`

#### From here you have 3 options
1. Upload the outputed zip to [https://archipelago.randomstuff.cc](https://archipelago.randomstuff.cc) (the official website won't work due to a 64MB file upload limit)
   - IF YOU USE THIS, THE WEBSOCKET URL IS NOT `archipelago.randomstuff.cc`, YOU NEED TO INPUT `ap.randomstuff.cc:PORT` INTO YOUR CLIENT
2. Host locally (requires port forwarding or everyone being on the same LAN)
3. Unzip the outputed zip file and remove the patch file
   - Unzip the generated `.zip` file
   - Copy the `.apsshd` file to another spot
   - Delete it from the unziped folder and rezip
   - Now extract `.apsshd` and copy `romfs` and `exefs` to your Ryujinx mod directory (located at `C:\Users\Your_Username\AppData\Roaming\Ryujinx\sdcard\atmosphere\contents\01002da013484000\Archipelago` on Windows - you will need to create the `Archipelago` folder)
   - You can now delete the patch file and upload the rezipped `.zip` file to [archipelago.gg](https://archipelago.gg)

### 4. Open Ryujinx
Make sure the mod and 1.0.1 update are enabled and open Skyward Sword HD

You should see the custom Archipelago logo - that means it's working

Get into the game far enough to where you can move Link

### 4. Launch the Client
Double click `launch_sshd.bat` if on Windows or run `python launch_sshd_wrapper.py` if on Linux/macOS

### 5. Play!
Items you find are automatically sent to other players and vice-versa!

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

### Development Setup

1. Fork this repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

##  License

This project is licensed under the AGPL License - see the [LICENSE](LICENSE) for details.

## Credits

- **Archipelago Team**: For the amazing multiworld randomizer framework
- **SSHD Randomizer Team**: For the original SSHD randomizer logic and the very helpful cheat table
- **Contributors**: Everyone who has helped improve this project

## Support

- **Discord**: Join the [Lon Lon Labs Discord Server](https://discord.gg/VeccXh4ydN)
- **Issues**: Report bugs on [GitHub Issues](https://github.com/LonLon-Labs/SSHD_APWorld/issues)
- **Official Website**: [archipelago.gg](https://archipelago.gg)

## Disclaimer

This project is not affiliated with or endorsed by Nintendo. You must own a legal copy of The Legend of Zelda: Skyward Sword HD to use this software.
