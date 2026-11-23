<div align="center">

# Guild Cloner

Copy selected parts of one Discord server into another from a single Nighty tab.

[![Script](https://img.shields.io/badge/NightyScript-Guild%20Cloner-5865F2?style=flat-square)](./guild_cloner.py)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://github.com/aboveproof/nighty-docs/blob/main/docs/python-runtime.md)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-227c57?style=flat-square)](./LICENSE)

</div>

## About

Guild Cloner is a NightyScript for rebuilding server structure, not for backing up conversations. Pick a source and a target, then choose what to copy. All toggles start off. The source is read-only; the live log shows what the cloner creates, skips, or fails to copy on the target.

> [!WARNING]
> Use this only for servers you are authorized to copy and administer. Automating a Discord user account can violate Discord's Terms of Service. This project is not affiliated with Discord or Nighty.

## Features

| What to copy | How it works |
| --- | --- |
| Channels and categories | Choose **Viewable** or **All** independently for each. Selecting **All** switches off its matching **Viewable** option. All means everything exposed to your client, not access to hidden names. |
| Permissions | Category overwrites, channel overwrites, and role permissions have separate switches. The cloner maps source roles and members to their target counterparts where possible. |
| Roles | Copies unmanaged roles. With role permissions enabled, it also updates the target's `@everyone` permissions. |
| Emojis and stickers | Uploads assets and skips names already present on the target. Discord's upload limits still apply. |
| Bots | Attempts authorization for missing bots. Failed bots' OAuth links are grouped under **needs manual auth** in a writable target channel. If none is available, check the run log. Bot settings and databases are not copied. |

The target dropdown shows servers where your account has **Manage Server**, **Manage Roles**, or **Manage Channels**. Selecting a target enables only the relevant controls: for example, Manage Channels alone does not enable role cloning or bot installation.

## Requirements and installation

1. Use a working [Nighty](https://nighty.one/) installation with scripting enabled. The script runs inside Nighty's Python runtime, not as a standalone Python program.
2. Download [`guild_cloner.py`](./guild_cloner.py) and place it in `%APPDATA%\nighty selfbot\data\scripts\` on Windows.
3. Load or reload the script in Nighty and open the **Guild Cloner** tab. The warning and update dialogs are built into this file; no separate UI script is required.

### Updates

Once per load, the script makes an unauthenticated request to read `SCRIPT_VERSION` from the `main` branch of [xmimiez/Guild-Cloner](https://github.com/xmimiez/Guild-Cloner). A newer version opens a notice showing both versions, with **Later** and **Open repository** actions. Updates are manual: nothing is installed or executed from GitHub. If the repository is private, unpublished, or unreachable, the cloner still works without update notices.

## Using the cloner

1. Select **Source server** and a different **Target server**. For a first run, use an empty test target.
2. Enable only what you want to copy. Leave both **Clear target** toggles off for an additive run.
3. Press **Start** and follow the current step and newest-first log. **Stop** finishes the current item; **KILL** cancels the in-progress task. Neither undoes requests Discord has already accepted.

> [!CAUTION]
> **Clear target channels** permanently deletes target channels, categories, and their message histories. **Clear target roles** deletes custom roles and their assignments. Cleanup requires the target owner's account and a separate confirmation naming the target and the resources. Changing the selection cancels that confirmation.

## Behavior and limits

- A matching name can cause an existing target item to be reused or skipped. A rerun is not a full synchronization or a rollback.
- Review permissions before inviting members to the target. Unmapped overwrites are omitted, and the cloner can retry creation without overwrites if Discord rejects them. A private source channel is not guaranteed to stay private on the target.
- Threads, messages, member assignments, and role icons are not cloned. Announcement channels are created as text channels.
- Cleanup, bot authorization, and manual-auth posts are paced. When Discord surfaces a rate limit, the script waits before retrying.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Target missing or toggle disabled | Check your effective server permissions. Reload Guild Cloner to rebuild the dropdown after a permission or membership change. |
| Bot not added | Look for **needs manual auth** in the target or the invite link in the run log. Review the permissions before authorizing. |
| Warning popup missing on mobile | If the client does not confirm that it displayed the CUI popup, look for the inline warning and **I understand** button. |

## Credits and license

Script author: **Mime | @N0_.q3**. The update workflow is inspired by [Nighty VC Manager](https://github.com/aboveproof/Nighty-VC-Manager). See also the [NightyScript documentation](https://github.com/aboveproof/nighty-docs).

Guild Cloner is licensed under the [PolyForm Noncommercial License 1.0.0](./LICENSE).
