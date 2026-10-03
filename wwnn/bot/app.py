"""Long-running Telegram bot (python-telegram-bot 22.x, long polling - no inbound port).

Handles button presses and a few commands. State lives in SQLite; the orchestrator service
picks up the state changes. Only user IDs in TELEGRAM_ALLOWED_USER_IDS may press buttons.
"""

from __future__ import annotations

from loguru import logger

from wwnn.bot import handlers
from wwnn.bot.keyboards import to_bot_api
from wwnn.config import Settings
from wwnn.db.migrate import open_db
from wwnn.orchestrator.state import State
from wwnn.util import iso_week


def build_application(settings: Settings):
    from telegram import InlineKeyboardMarkup, Update
    from telegram.constants import ParseMode
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

    conn = open_db(settings.db_path)

    def markup(rows):
        return InlineKeyboardMarkup.de_json(to_bot_api(rows), None) if rows else None

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        reply = handlers.handle_callback(conn, settings, q.from_user.id, q.data or "")
        await q.answer(reply.answer or None, show_alert=reply.alert)
        try:
            if reply.buttons_only:
                await q.edit_message_reply_markup(reply_markup=markup(reply.edit_buttons))
            elif reply.edit_text is not None:
                if q.message and q.message.text is not None:
                    await q.edit_message_text(reply.edit_text, parse_mode=ParseMode.HTML,
                                              reply_markup=markup(reply.edit_buttons))
                else:  # audio/document messages have captions, not text
                    await q.edit_message_reply_markup(reply_markup=None)
                    await q.message.reply_text(reply.edit_text, parse_mode=ParseMode.HTML)
        except Exception as e:  # "message is not modified" etc.
            logger.debug(f"edit failed: {e}")

    def allowed(update: Update) -> bool:
        return bool(update.effective_user) and handlers.authorized(settings, update.effective_user.id)

    async def cmd_start(update: Update, ctx) -> None:
        u, c = update.effective_user, update.effective_chat
        await update.message.reply_text(
            f"WWNN bot. Your user id: {u.id}, this chat id: {c.id}.\n"
            "Put them in TELEGRAM_ALLOWED_USER_IDS / TELEGRAM_CHAT_ID. Commands: /status, /newrun")

    async def cmd_status(update: Update, ctx) -> None:
        if allowed(update):
            await update.message.reply_text(handlers.status_text(conn))

    async def cmd_newrun(update: Update, ctx) -> None:
        if not allowed(update):
            return
        from wwnn.db import repo
        week = iso_week()
        if repo.active_run_for_week(conn, week):
            await update.message.reply_text(f"A run for {week} already exists. /status")
            return
        rid = repo.create_run(conn, week, settings.dry_run)
        await update.message.reply_text(f"Run #{rid} created for {week}; the orchestrator will send the stories.")

    async def cmd_cancel(update: Update, ctx) -> None:
        if not allowed(update) or not ctx.args:
            return
        from wwnn.db import repo
        try:
            ok = repo.set_state(conn, int(ctx.args[0]), State.CANCELLED)
        except Exception as e:
            ok = False
            logger.info(f"cancel failed: {e}")
        await update.message.reply_text("Cancelled." if ok else "Could not cancel.")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("newrun", cmd_newrun))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    return app


def main() -> None:
    settings = Settings.from_env()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not settings.allowed_user_ids:
        logger.warning("TELEGRAM_ALLOWED_USER_IDS is empty: every button press will be refused. "
                       "Send /start to the bot to learn your user id.")
    build_application(settings).run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
