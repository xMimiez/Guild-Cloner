@nightyScript(
    name="Guild Cloner",
    author="Mime | @N0_.q3",
    description="Clone channels, categories, roles, emojis, stickers, bots and permissions from one server into another.",
    usage="Open the Guild Cloner tab"
)
def guild_cloner():
    """
    GUILD CLONER
    ------------

    Pick a source and a target server, choose what to copy, press Start.

    CONTROLS:
    Start - begins the clone. Disabled until the run ends.
    Stop  - finishes the task in progress, then stops before the next one.
    KILL  - cancels the action in progress immediately.

    NOTES:
    - Unless owner-confirmed cleanup is selected, roles, categories, channels,
      emojis and stickers that already exist there by name are reused or
      skipped, so a stopped run can be started again.
    - "Viewable" means the selected account has View Channel on it.
    - Bots cannot be added silently. The cloner asks Discord to authorise each
      bot and logs an invite link when Discord refuses (usually a captcha).
    """
    import asyncio
    import io
    import json
    import re
    import uuid
    from datetime import datetime

    SCRIPT = "Guild Cloner"
    SCRIPT_VERSION = "1.0.0"
    PROJECT_URL = "https://github.com/xmimiez/Guild-Cloner"
    VERSION_SOURCE = "https://raw.githubusercontent.com/xmimiez/Guild-Cloner/main/guild_cloner.py"
    RUNTIME_KEY = "_guild_cloner_runtime"
    MAX_LOG_LINES = 300
    ALL_WARNING = (
        "Due to discord's recent patch almost all users cannot see the channel or category names "
        "but permissions are still viewable. clone at your own risk"
    )

    # ==================== RELOAD-SAFE RUNTIME ====================

    previous = getattr(bot, RUNTIME_KEY, None)
    if isinstance(previous, dict):
        previous["closed"] = True
        for old_task in list(previous.get("tasks", set())):
            try:
                if old_task and not old_task.done():
                    old_task.cancel()
            except Exception:
                pass

    runtime = {
        "closed": False,
        "tasks": set(),
        "job": None,
        "running": False,
        "stop": False,
        "status": "Idle",
        "lines": [],
        "source_id": None,
        "target_id": None,
    }
    setattr(bot, RUNTIME_KEY, runtime)

    options = {
        "viewable_channels": False,
        "all_channels": False,
        "viewable_categories": False,
        "all_categories": False,
        "roles": False,
        "emojis": False,
        "stickers": False,
        "bots": False,
        "channel_perms": False,
        "category_perms": False,
        "role_perms": False,
        "clear_channels": False,
        "clear_roles": False,
    }

    class StopClone(Exception):
        pass

    def push_state():
        if runtime["closed"]:
            return
        start_button.disabled = runtime["running"]
        stop_button.disabled = not runtime["running"] or runtime["stop"]
        kill_button.disabled = not runtime["running"]
        status_text.content = f"Current step: {runtime['status']}"

    def log(message, level="info"):
        if runtime["closed"]:
            return
        runtime["log_seq"] = runtime.get("log_seq", 0) + 1
        line = {"id": str(runtime["log_seq"]), "cells": [{
            "text": str(message)[:500], "subtext": f"{datetime.now():%H:%M:%S}  {level.upper()}",
        }]}
        runtime["lines"].append(line)
        del runtime["lines"][:-MAX_LOG_LINES]
        log_table.rows = list(reversed(runtime["lines"]))

    def set_status(text):
        runtime["status"] = str(text)[:160]
        push_state()

    def step(text):
        set_status(text)
        log(text, "step")

    def toast(title, description, kind="INFO"):
        try:
            tab.toast(title=title, description=description, type=kind)
        except Exception:
            pass

    # CUI and native callbacks can arrive on a worker thread.
    def run_on_loop(coroutine):
        def start():
            try:
                task = bot.loop.create_task(coroutine)
            except Exception as e:
                coroutine.close()
                print(f"[{SCRIPT}] Task error: {e}", type_="ERROR")
                return
            runtime["tasks"].add(task)
            task.add_done_callback(runtime["tasks"].discard)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        try:
            if running is bot.loop:
                start()
            else:
                bot.loop.call_soon_threadsafe(start)
        except Exception as e:
            coroutine.close()
            print(f"[{SCRIPT}] Task error: {e}", type_="ERROR")

    # ==================== CLONE HELPERS ====================

    def checkpoint():
        if runtime["stop"] or runtime["closed"]:
            raise StopClone()

    def kind_of(channel):
        channel_type = getattr(channel, "type", None)
        return getattr(channel_type, "name", str(channel_type))

    def can_view(channel, me):
        if me is None:
            return False
        try:
            return bool(channel.permissions_for(me).view_channel)
        except Exception:
            return False

    def build_overwrites(channel, source, target, role_map, enabled):
        overwrites = {}
        if not enabled:
            return overwrites
        try:
            items = list(channel.overwrites.items())
        except Exception:
            return overwrites
        for principal, overwrite in items:
            principal_id = getattr(principal, "id", None)
            if principal_id == source.id:
                overwrites[target.default_role] = overwrite
            elif principal_id in role_map:
                overwrites[role_map[principal_id]] = overwrite
            elif source.get_role(principal_id) is None:
                member = target.get_member(principal_id)
                if member is not None:
                    overwrites[member] = overwrite
        return overwrites

    async def create_with_fallback(label, factory, overwrites):
        """Create with overwrites; if Discord rejects them, create without and say so."""
        try:
            return await factory(overwrites)
        except Exception as e:
            if not overwrites:
                raise
            log(f"{label}: permissions rejected ({e}). Creating without them.", "warn")
            await asyncio.sleep(0.6)
            return await factory({})

    async def clone_roles(source, target, opts, role_map):
        roles = sorted(
            (r for r in source.roles if not r.is_default() and not r.managed),
            key=lambda r: r.position,
            reverse=True,
        )
        existing = {r.name: r for r in target.roles if not r.is_default() and not r.managed}
        no_permissions = type(source.default_role.permissions).none()
        # New roles appear at the bottom, so creating from the top down keeps the order.
        for index, role in enumerate(roles, start=1):
            checkpoint()
            set_status(f"Roles {index}/{len(roles)}: {role.name}")
            if role.name in existing:
                role_map[role.id] = existing[role.name]
                log(f"Role already exists, reusing: {role.name}")
                continue
            fields = {
                "name": role.name,
                "colour": role.colour,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "permissions": role.permissions if opts["role_perms"] else no_permissions,
            }
            try:
                try:
                    new_role = await target.create_role(**fields)
                except Exception as e:
                    if not opts["role_perms"]:
                        raise
                    log(f"Role {role.name}: permissions rejected ({e}). Creating without them.", "warn")
                    await asyncio.sleep(0.6)
                    fields["permissions"] = no_permissions
                    new_role = await target.create_role(**fields)
                role_map[role.id] = new_role
                existing[role.name] = new_role
                log(f"Role created: {role.name}", "ok")
            except Exception as e:
                log(f"Role failed: {role.name}: {e}", "error")
            await asyncio.sleep(0.8)

        if opts["role_perms"]:
            checkpoint()
            set_status("Roles: @everyone permissions")
            try:
                await target.default_role.edit(permissions=source.default_role.permissions)
                log("@everyone permissions copied.", "ok")
            except Exception as e:
                log(f"@everyone permissions failed: {e}", "error")
            await asyncio.sleep(0.6)

    def map_roles_by_name(source, target, role_map):
        by_name = {r.name: r for r in target.roles if not r.is_default()}
        for role in source.roles:
            if role.id not in role_map and not role.is_default() and role.name in by_name:
                role_map[role.id] = by_name[role.name]

    async def clone_categories(source, target, opts, role_map, category_map, me):
        categories = sorted(source.categories, key=lambda c: c.position)
        if not opts["all_categories"]:
            categories = [
                c for c in categories
                if can_view(c, me) or any(can_view(child, me) for child in c.channels)
            ]
        existing = {c.name: c for c in target.categories}
        for index, category in enumerate(categories, start=1):
            checkpoint()
            set_status(f"Categories {index}/{len(categories)}: {category.name}")
            if category.name in existing:
                category_map[category.id] = existing[category.name]
                log(f"Category already exists, reusing: {category.name}")
                continue
            overwrites = build_overwrites(category, source, target, role_map, opts["category_perms"])
            try:
                new_category = await create_with_fallback(
                    f"Category {category.name}",
                    lambda ow, c=category: target.create_category(name=c.name, overwrites=ow),
                    overwrites,
                )
                category_map[category.id] = new_category
                existing[category.name] = new_category
                log(f"Category created: {category.name}", "ok")
            except Exception as e:
                log(f"Category failed: {category.name}: {e}", "error")
            await asyncio.sleep(0.8)

    async def clone_channels(source, target, opts, role_map, category_map, me):
        channels = [c for c in source.channels if kind_of(c) != "category"]
        if not opts["all_channels"]:
            channels = [c for c in channels if can_view(c, me)]

        def order(channel):
            category = getattr(channel, "category", None)
            return (
                category.position if category else -1,
                1 if kind_of(channel) in ("voice", "stage_voice") else 0,
                channel.position,
            )

        channels.sort(key=order)
        target_categories = {c.name: c for c in target.categories}
        existing = {(c.name, kind_of(c), getattr(c, "category_id", None)) for c in target.channels}

        for index, channel in enumerate(channels, start=1):
            checkpoint()
            kind = kind_of(channel)
            set_status(f"Channels {index}/{len(channels)}: {channel.name}")

            parent = None
            source_category = getattr(channel, "category", None)
            if source_category is not None:
                parent = category_map.get(source_category.id) or target_categories.get(source_category.name)

            new_kind = "text" if kind == "news" else kind
            if (channel.name, new_kind, parent.id if parent else None) in existing:
                log(f"Channel already exists, skipping: {channel.name}")
                continue

            overwrites = build_overwrites(channel, source, target, role_map, opts["channel_perms"])

            if kind in ("text", "news"):
                fields = {"nsfw": bool(getattr(channel, "nsfw", False))}
                if getattr(channel, "topic", None):
                    fields["topic"] = channel.topic
                if getattr(channel, "slowmode_delay", 0):
                    fields["slowmode_delay"] = channel.slowmode_delay
                factory = lambda ow, c=channel, f=fields, p=parent: target.create_text_channel(
                    c.name, overwrites=ow, category=p, **f)
            elif kind == "voice":
                fields = {
                    "bitrate": min(int(getattr(channel, "bitrate", 64000)), int(target.bitrate_limit)),
                    "user_limit": int(getattr(channel, "user_limit", 0) or 0),
                }
                factory = lambda ow, c=channel, f=fields, p=parent: target.create_voice_channel(
                    c.name, overwrites=ow, category=p, **f)
            elif kind == "stage_voice":
                factory = lambda ow, c=channel, p=parent: target.create_stage_channel(
                    c.name, overwrites=ow, category=p)
            elif kind in ("forum", "media"):
                fields = {"nsfw": bool(getattr(channel, "nsfw", False))}
                if getattr(channel, "topic", None):
                    fields["topic"] = channel.topic
                if kind == "media":
                    fields["media"] = True
                factory = lambda ow, c=channel, f=fields, p=parent: target.create_forum(
                    c.name, overwrites=ow, category=p, **f)
            else:
                log(f"Channel type '{kind}' is not supported, skipping: {channel.name}", "warn")
                continue

            try:
                await create_with_fallback(f"Channel {channel.name}", factory, overwrites)
                existing.add((channel.name, new_kind, parent.id if parent else None))
                log(f"Channel created ({kind}): {channel.name}", "ok")
            except Exception as e:
                log(f"Channel failed ({kind}): {channel.name}: {e}", "error")
            await asyncio.sleep(0.9)

    async def clone_emojis(source, target):
        emojis = list(source.emojis)
        existing = {e.name for e in target.emojis}
        for index, emoji in enumerate(emojis, start=1):
            checkpoint()
            set_status(f"Emojis {index}/{len(emojis)}: {emoji.name}")
            if emoji.name in existing:
                log(f"Emoji already exists, skipping: {emoji.name}")
                continue
            try:
                image = await emoji.read()
                await target.create_custom_emoji(name=emoji.name, image=image)
                existing.add(emoji.name)
                log(f"Emoji created: {emoji.name}", "ok")
            except Exception as e:
                log(f"Emoji failed: {emoji.name}: {e}", "error")
            await asyncio.sleep(1.2)

    async def clone_stickers(source, target):
        stickers = list(source.stickers)
        existing = {s.name for s in target.stickers}
        for index, sticker in enumerate(stickers, start=1):
            checkpoint()
            set_status(f"Stickers {index}/{len(stickers)}: {sticker.name}")
            if sticker.name in existing:
                log(f"Sticker already exists, skipping: {sticker.name}")
                continue
            try:
                data = await sticker.read()
                fmt = getattr(getattr(sticker, "format", None), "name", "png")
                extension = {"lottie": "json", "gif": "gif"}.get(fmt, "png")
                await target.create_sticker(
                    name=sticker.name,
                    description=getattr(sticker, "description", None) or sticker.name,
                    emoji=getattr(sticker, "emoji", None) or "star",
                    file=discord.File(io.BytesIO(data), filename=f"sticker.{extension}"),
                )
                existing.add(sticker.name)
                log(f"Sticker created: {sticker.name}", "ok")
            except Exception as e:
                log(f"Sticker failed: {sticker.name}: {e}", "error")
            await asyncio.sleep(1.5)

    async def paced(operation, gap=1.5):
        """Space mutations apart and respect cooldowns surfaced by the Discord client."""
        loop = asyncio.get_running_loop()
        for attempt in range(3):
            while (wait := runtime.get("next_request", 0) - loop.time()) > 0:
                checkpoint()
                await asyncio.sleep(min(wait, 0.5))
            checkpoint()
            try:
                result = await operation()
            except Exception as error:
                response = getattr(error, "response", None)
                retry = getattr(error, "retry_after", None)
                limited = getattr(error, "status", None) == 429 or retry is not None
                if not limited:
                    runtime["next_request"] = loop.time() + gap
                    raise
                headers = getattr(response, "headers", {}) or {}
                try:
                    retry = float(retry or headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    retry = 0
                wait = max(gap * 2 ** (attempt + 1), retry) + 0.5
                runtime["next_request"] = loop.time() + wait
                log(f"Discord rate limit: pausing for {wait:.1f}s.", "warn")
                if attempt == 2:
                    raise
            else:
                runtime["next_request"] = loop.time() + gap
                return result

    async def clear_target(source, target, opts, confirmation):
        if not (opts["clear_channels"] or opts["clear_roles"]):
            return
        if source.id == target.id or target.owner_id != bot.user.id or confirmation != str(target.id):
            raise ValueError("Cleanup requires the target owner's account and confirmation for this target.")
        items = []
        if opts["clear_channels"]:
            items.extend(sorted(target.channels, key=lambda c: kind_of(c) == "category"))
        if opts["clear_roles"]:
            items.extend(r for r in target.roles if not r.is_default() and not r.managed)
        for index, item in enumerate(items, 1):
            checkpoint()
            if item.guild.id != target.id or target.owner_id != bot.user.id:
                raise ValueError("Target ownership or identity changed; cleanup stopped.")
            step(f"Clearing {index}/{len(items)}: {item.name} ({item.id})")
            await paced(lambda: item.delete(reason="Owner-confirmed Guild Cloner cleanup"))
        checkpoint()

    async def post_manual_auth(target, links):
        if not links:
            return
        label = "needs manual auth"
        pages = [label]
        for link in links:
            entry = f"\n<{link}>"
            if len(pages[-1]) + len(entry) > 2000:
                pages.append(label)
            pages[-1] += entry
        channels = [c for c in target.text_channels if target.me and
                    can_view(c, target.me) and c.permissions_for(target.me).send_messages]
        for page in pages:
            while channels:
                channel = channels[0]
                try:
                    await paced(lambda: channel.send(page))
                except StopClone:
                    raise
                except Exception as error:
                    if getattr(error, "status", None) in (403, 404):
                        channels.pop(0)
                        continue
                    log("Could not deliver the manual-auth report. Links are in the run log.", "warn")
                    return
                log(f"Posted manual-auth links in #{channel.name}.", "ok")
                break
            else:
                log("No writable target text channel. Manual-auth links are in the run log.", "warn")
                return

    async def clone_bots(source, target, opts):
        found = {}
        for role in source.roles:
            bot_id = getattr(getattr(role, "tags", None), "bot_id", None)
            if bot_id:
                found[bot_id] = (role.name, role.permissions)
        for member in source.members:
            if getattr(member, "bot", False) and member.id not in found:
                found[member.id] = (member.name, None)
        if not found:
            log("No bots found on the source server.", "warn")
            return

        links = []
        for index, (bot_id, (name, permissions)) in enumerate(found.items(), start=1):
            checkpoint()
            set_status(f"Bots {index}/{len(found)}: {name}")
            if target.get_member(bot_id) is not None:
                log(f"Bot already on the target, skipping: {name}")
                continue
            fields = {"scopes": ["bot", "applications.commands"], "guild": target}
            link = (
                f"https://discord.com/oauth2/authorize?client_id={bot_id}"
                f"&scope=bot%20applications.commands&guild_id={target.id}&disable_guild_select=true"
            )
            if permissions is not None and opts["role_perms"]:
                fields["permissions"] = permissions
                link += f"&permissions={permissions.value}"
            try:
                await paced(lambda: bot.create_authorization(bot_id, **fields), gap=3)
                log(f"Bot added: {name}", "ok")
            except StopClone:
                raise
            except Exception:
                links.append(link)
                log(f"needs manual auth - {name}: {link}", "warn")
        await post_manual_auth(target, links)

    async def run_clone(source, target, opts):
        me = source.me or source.get_member(bot.user.id)
        wants_viewable = (
            (opts["viewable_channels"] and not opts["all_channels"])
            or (opts["viewable_categories"] and not opts["all_categories"])
        )
        if me is None and wants_viewable:
            log("Could not resolve your member on the source server, so nothing counts as viewable.", "warn")

        role_map = {}
        category_map = {}
        do_categories = opts["viewable_categories"] or opts["all_categories"]
        do_channels = opts["viewable_channels"] or opts["all_channels"]

        if opts["roles"]:
            step("Cloning roles")
            await clone_roles(source, target, opts, role_map)
        if do_categories or do_channels:
            map_roles_by_name(source, target, role_map)
        if do_categories:
            checkpoint()
            step("Cloning categories" + (" (all)" if opts["all_categories"] else " (viewable)"))
            await clone_categories(source, target, opts, role_map, category_map, me)
        if do_channels:
            checkpoint()
            step("Cloning channels" + (" (all)" if opts["all_channels"] else " (viewable)"))
            await clone_channels(source, target, opts, role_map, category_map, me)
        if opts["emojis"]:
            checkpoint()
            step("Cloning emojis")
            await clone_emojis(source, target)
        if opts["stickers"]:
            checkpoint()
            step("Cloning stickers")
            await clone_stickers(source, target)
        if opts["bots"]:
            checkpoint()
            step("Adding bots")
            await clone_bots(source, target, opts)

    async def job_main(source_id, target_id, opts, confirmation):
        runtime["job"] = asyncio.current_task()
        try:
            content_keys = ("viewable_channels", "all_channels", "viewable_categories", "all_categories",
                            "roles", "emojis", "stickers", "bots", "clear_channels", "clear_roles")
            problem = None
            source = bot.get_guild(int(source_id)) if source_id else None
            target = bot.get_guild(int(target_id)) if target_id else None
            if source is None or target is None:
                problem = "Select a source server and a target server."
            elif source.id == target.id:
                problem = "Source and target must be different servers."
            elif {key for key, enabled in opts.items() if enabled} - allowed_options(target):
                if runtime["target_id"] == target_id:
                    refresh_target_controls(target)
                problem = "The target permissions changed. Review the available options before starting."
            elif not any(opts[key] for key in content_keys):
                problem = "Turn on at least one thing to clone."
            if problem:
                log(problem, "error")
                set_status("Idle")
                toast("Cannot start", problem, "ERROR")
                return

            checkpoint()
            if opts["clear_channels"] or opts["clear_roles"]:
                reset_cleanup()
                await clear_target(source, target, opts, confirmation)
            step(f"Starting: {source.name} -> {target.name}")
            await run_clone(source, target, opts)
            log("Clone complete.", "ok")
            set_status("Complete")
            toast("Clone complete", f"{source.name} -> {target.name}", "SUCCESS")
        except StopClone:
            log("Stopped before the next task.", "warn")
            set_status("Stopped")
        except asyncio.CancelledError:
            log("KILLED: the action in progress was cancelled.", "error")
            set_status("Killed")
        except Exception as e:
            log(f"Unexpected error: {e}", "error")
            set_status("Failed")
            print(f"[{SCRIPT}] Clone failed: {e}", type_="ERROR")
        finally:
            runtime["running"] = False
            runtime["stop"] = False
            runtime["job"] = None
            push_state()

    # ==================== CONTROL CALLBACKS ====================

    def launch(selection, confirmation=None):
        if runtime["running"] or runtime["closed"]:
            return
        runtime["running"] = True
        runtime["stop"] = False
        runtime["status"] = "Starting"
        push_state()
        run_on_loop(job_main(*selection, confirmation))

    def selection():
        return runtime["source_id"], runtime["target_id"], dict(options)

    def cancel_confirmation(_value=None):
        if runtime.pop("pending_cleanup", None) is not None:
            confirm_button.visible = cancel_button.visible = False

    def confirm_cleanup(_value=None):
        pending = runtime.get("pending_cleanup")
        cancel_confirmation()
        if pending and pending == selection():
            launch(pending, str(pending[1]))

    def on_start(_value=None):
        if runtime["running"] or runtime["closed"]:
            return
        chosen = selection()
        source_id, target_id, opts = chosen
        if opts["clear_channels"] or opts["clear_roles"]:
            target = bot.get_guild(int(target_id)) if target_id else None
            if not target or not source_id or source_id == target_id or target.owner_id != bot.user.id:
                toast("Cannot clear target", "Choose a different target server that you own.", "ERROR")
                return
            scope = " and ".join(label for key, label in (
                ("clear_channels", "channels and categories"), ("clear_roles", "custom roles")
            ) if opts[key])
            confirm_button.label = f"Delete {scope} from {target.name} ({target.id})"
            runtime["pending_cleanup"] = chosen
            confirm_button.visible = cancel_button.visible = True
            return
        launch(chosen)

    def on_stop(_value=None):
        if not runtime["running"] or runtime["stop"]:
            return
        runtime["stop"] = True
        log("Stop requested: finishing the current task, then stopping.", "warn")
        set_status("Stopping after the current task")

    def on_kill(_value=None):
        if not runtime["running"]:
            return
        runtime["stop"] = True
        job = runtime["job"]
        if job is not None and not job.done():
            bot.loop.call_soon_threadsafe(job.cancel)

    # ==================== TAB ====================

    tab = Tab(name="Guild Cloner", icon="convert", title="Guild Cloner", gap=4)
    page = tab.create_container(type="rows", width="full", height="auto", gap=4)

    # --- Area 1: servers ---
    toggle_controls = {}
    scope_pairs = {"all_channels": "viewable_channels", "all_categories": "viewable_categories"}

    def allowed_options(guild):
        if guild is None or guild.me is None:
            return set()
        if guild.owner_id == bot.user.id:
            return set(options)
        perms = guild.me.guild_permissions
        allowed = set()
        if perms.manage_channels:
            allowed.update(("viewable_channels", "all_channels", "channel_perms",
                            "viewable_categories", "all_categories", "category_perms"))
        if perms.manage_roles:
            allowed.update(("roles", "role_perms"))
        if perms.manage_guild:
            allowed.add("bots")
        if perms.create_expressions:
            allowed.update(("emojis", "stickers"))
        # Cleanup is already restricted to the target owner by clear_target.
        return allowed

    def refresh_target_controls(guild):
        allowed = allowed_options(guild)
        for all_key, viewable_key in scope_pairs.items():
            if options[all_key]:
                allowed.discard(viewable_key)
        for key, toggle in toggle_controls.items():
            toggle.disabled = key not in allowed
            if key not in allowed and options[key]:
                options[key] = False
                toggle.checked = False

    server_items = []
    target_items = []
    for guild in sorted(bot.guilds, key=lambda g: g.name.lower()):
        item = {"id": str(guild.id), "title": guild.name}
        if guild.icon:
            item["iconUrl"] = guild.icon.url
        server_items.append(item)
        permissions = getattr(guild.me, "guild_permissions", None)
        # Discord uses Manage Channels for categories as well.
        if permissions and (permissions.manage_guild or permissions.manage_roles or permissions.manage_channels):
            target_items.append(item)

    servers = page.create_container(type="columns", width="full", height="auto", gap=4)

    def bind_change(control, key, handler):
        # Nighty's callback bridge needs a distinct name for each generated handler.
        handler.__name__ = handler.__qualname__ = f"guild_cloner_change_{key}"
        control.onChange = handler

    def toggle_changed(key, checked):
        enabled = checked is True or str(checked).lower() in ("true", "1")
        if options[key] == enabled:
            return False
        options[key] = enabled
        return True

    def server_card(title, subtitle, label, key, items):
        card = servers.create_card(width="full", height="auto", gap=3)
        card.create_ui_element(UI.Text, content=title, size="lg", weight="bold")
        card.create_ui_element(UI.Text, content=subtitle, size="sm", color="#8B8B9E")
        select = card.create_ui_element(
            UI.Select, label=label, items=items, selected_items=[], mode="single", full_width=True)

        def changed(selected):
            value = selected[0] if selected else None
            if value != runtime[key]:
                cancel_confirmation()
            if key == "target_id" and value != runtime[key]:
                reset_cleanup()
            runtime[key] = value
            if key == "target_id":
                refresh_target_controls(bot.get_guild(int(value)) if value else None)

        bind_change(select, key, changed)

    server_card("Source server", "The server to copy from.", "Source server", "source_id", server_items)
    server_card("Target server", "Requires Manage Server, Manage Roles, or Manage Channels. Cleanup is optional and irreversible.",
                "Target server", "target_id", target_items)

    # --- Area 2: what to clone ---
    parts = page.create_card(width="full", height="auto", gap=3)
    parts.create_ui_element(UI.Text, content="What to clone", size="lg", weight="bold")
    parts.create_ui_element(
        UI.Text,
        content="Viewable means your account has View Channel. An All toggle includes everything its Viewable toggle does.",
        size="sm", color="#8B8B9E")
    # Native clients may silently ignore evaluate_js. Show a native acknowledgement
    # only when the browser has not confirmed rendering the popup.
    fallback_notices = {}
    notice_text = parts.create_ui_element(UI.Text, content="Warning", visible=False)
    notice_button = parts.create_ui_element(UI.Button, label="I understand", visible=False)

    def refresh_fallback():
        if fallback_notices:
            notice_text.content = next(iter(fallback_notices.values()))
        notice_text.visible = notice_button.visible = bool(fallback_notices)

    def guild_cloner_ack_warning():
        if fallback_notices:
            token = next(iter(fallback_notices))
            pending_notices.discard(token)
            del fallback_notices[token]
            refresh_fallback()

    notice_button.onClick = guild_cloner_ack_warning

    pending_notices = set()

    def guild_cloner_notice_rendered(token):
        if token in pending_notices:
            pending_notices.discard(token)
            if token in fallback_notices:
                del fallback_notices[token]
                refresh_fallback()

    def show_notice(title, message, update=False):
        if runtime["closed"]:
            return
        token = uuid.uuid4().hex
        pending_notices.add(token)
        payload = json.dumps([title, message, PROJECT_URL if update else None, token])
        try:
            evaluate_js("""(([title, message, url, token]) => {
                const dialog = document.createElement('dialog');
                dialog.setAttribute('aria-label', title);
                dialog.style.cssText = 'position:fixed;inset:0;margin:auto;width:min(90vw,28rem);height:fit-content;box-sizing:border-box;padding:22px;border:1px solid #53586b;border-radius:12px;background:#191b23;color:#eee;z-index:10000';
                const heading = document.createElement('strong');
                heading.textContent = title;
                const body = document.createElement('p');
                body.textContent = message;
                const dismiss = document.createElement('button');
                dismiss.textContent = url ? 'Later' : 'I understand';
                dismiss.onclick = () => dialog.remove();
                dialog.append(heading, body, dismiss);
                if (url) {
                    const link = document.createElement('a');
                    link.textContent = 'Open repository';
                    link.href = url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.style.cssText = 'margin-left:16px;color:#aacaff';
                    dialog.append(link);
                }
                document.body.append(dialog);
                if (typeof dialog.showModal === 'function') dialog.showModal();
                else dialog.setAttribute('open', '');
                window.pywebview?.api?.customCallback('guild_cloner_notice_rendered', token);
            })(""" + payload + ");")
        except Exception:
            pass

        async def check_delivery():
            await asyncio.sleep(3)
            if token in pending_notices and not runtime["closed"]:
                fallback_notices[token] = f"{title}: {message}" + (f" {PROJECT_URL}" if update else "")
                refresh_fallback()

        run_on_loop(check_delivery())

    async def check_update():
        try:
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                async with session.get(VERSION_SOURCE) as response:
                    if response.status != 200:
                        return
                    # The version declaration lives in the script header. Never execute remote code.
                    size = 0
                    async for line in response.content:
                        size += len(line)
                        if size > 16384 or len(line) > 4096:
                            return
                        match = re.fullmatch(rb'\s*SCRIPT_VERSION\s*=\s*"(\d{1,6}\.\d{1,6}\.\d{1,6})"\s*', line)
                        if match:
                            latest = match[1].decode("ascii")
                            if tuple(map(int, latest.split("."))) > tuple(map(int, SCRIPT_VERSION.split("."))):
                                show_notice("Guild Cloner update available",
                                            f"Installed: v{SCRIPT_VERSION}. Available: v{latest}. "
                                            "Replace guild_cloner.py and reload it in Nighty.", update=True)
                            return
        except (ImportError, OSError, asyncio.TimeoutError, ValueError):
            return
        except aiohttp.ClientError:
            return

    def add_toggle(group, key, label, warning=None):
        toggle = group.create_ui_element(UI.Toggle, label=label, checked=options[key], disabled=True)
        toggle_controls[key] = toggle

        def changed(checked):
            if toggle.disabled:
                return
            if not toggle_changed(key, checked):
                return
            cancel_confirmation()
            if key in scope_pairs:
                target_id = runtime["target_id"]
                refresh_target_controls(bot.get_guild(int(target_id)) if target_id else None)
            if warning and options[key]:
                show_notice(label, warning)

        bind_change(toggle, key, changed)
        return toggle

    def toggle_section(title, entries):
        parts.create_ui_element(UI.Text, content=title, size="sm", weight="bold", color="#8B8B9E")
        for entry in entries:
            add_toggle(parts, *entry)

    toggle_section("Channels", [
        ("viewable_channels", "Viewable channels"),
        ("all_channels", "All channels", ALL_WARNING),
        ("channel_perms", "Channel permissions"),
    ])
    toggle_section("Categories", [
        ("viewable_categories", "Viewable categories"),
        ("all_categories", "All categories", ALL_WARNING),
        ("category_perms", "Category permissions"),
    ])
    toggle_section("Roles", [
        ("roles", "Roles"),
        ("role_perms", "Role permissions"),
    ])
    toggle_section("Extras", [
        ("emojis", "Emojis"),
        ("stickers", "Stickers"),
        ("bots", "Bots", "The cloner will attempt to add bots to the target server. "
         "If any fail, it will post their OAuth invite links under 'needs manual auth' in a writable "
         "target channel. If it cannot post there, the links will remain in the run log."),
    ])

    cleanup = page.create_card(width="full", height="auto", gap=2)
    cleanup.create_ui_element(UI.Text, content="Clear target before cloning", weight="bold")
    cleanup_controls = {}

    def reset_cleanup():
        cancel_confirmation()
        for key, toggle in cleanup_controls.items():
            options[key] = False
            toggle.checked = False

    def cleanup_toggle(key, label, warning):
        cleanup_controls[key] = add_toggle(
            cleanup, key, label, warning + " This cannot be undone. "
            "Start will ask you to confirm the target and what will be deleted.")

    cleanup_toggle("clear_channels", "Clear target channels", "Deletes target channels and categories, including message history.")
    cleanup_toggle("clear_roles", "Clear target roles", "Deletes target roles and their assignments, except @everyone and managed roles.")

    # --- Area 3: controls and live log ---
    control = page.create_card(width="full", height="auto", gap=3)
    control.create_ui_element(UI.Text, content="Run", size="lg", weight="bold")
    # These controls must render without the desktop JavaScript bridge.
    start_button = control.create_ui_element(UI.Button, label="Start", color="success", full_width=True)
    confirm_button = control.create_ui_element(UI.Button, label="Confirm deletion", color="danger", full_width=True, visible=False)
    cancel_button = control.create_ui_element(UI.Button, label="Cancel cleanup", full_width=True, visible=False)
    stop_button = control.create_ui_element(UI.Button, label="Stop", color="primary", full_width=True, disabled=True)
    kill_button = control.create_ui_element(UI.Button, label="KILL", color="danger", full_width=True, disabled=True)
    for button, handler in ((start_button, on_start), (confirm_button, confirm_cleanup),
                            (cancel_button, cancel_confirmation), (stop_button, on_stop), (kill_button, on_kill)):
        handler.__name__ = f"guild_cloner_{handler.__name__}"
        button.onClick = handler
    status_text = control.create_ui_element(UI.Text, content="Current step: Idle")
    log_table = control.create_ui_element(
        UI.Table, columns=[{"type": "text", "label": "Live log (newest first)"}],
        rows=[], items_per_page=10, selectable=False)

    tab.render()
    callback_store.register(guild_cloner_notice_rendered)
    run_on_loop(check_update())

guild_cloner()
