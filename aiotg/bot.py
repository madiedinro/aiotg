import os
import re
import logging
import asyncio
from urllib.parse import splitpasswd, splituser, urlparse

import aiohttp
from aiohttp import web
from aiosocksy import Socks4Auth, Socks5Auth, connector as socks_connector
import json
from collections import defaultdict
from types import AsyncGeneratorType, CoroutineType

from aiohttp import ClientSession

try:
    import certifi
    import ssl
except ImportError:
    certifi = None


from .chat import Chat, Sender, AsyncChatContext, StopChatContext
from .reloader import run_with_reloader

__author__ = "Stepan Zastupov"
__copyright__ = "Copyright 2015-2017 Stepan Zastupov"
__license__ = "MIT"

API_URL = "https://api.telegram.org"
API_TIMEOUT = 60
RETRY_TIMEOUT = 30
RETRY_CODES = [429, 500, 502, 503, 504]
CHATBASE_URL = "https://chatbase.com/api/message"

# Message types to be handled by bot.handle(...)
MESSAGE_TYPES = [
    "location",
    "photo",
    "document",
    "audio",
    "voice",
    "sticker",
    "contact",
    "venue",
    "video",
    "game",
    "delete_chat_photo",
    "new_chat_photo",
    "delete_chat_photo",
    "new_chat_member",
    "left_chat_member",
    "new_chat_title",
    "group_chat_created",
    "successful_payment",
]

# Update types for
MESSAGE_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "successful_payment",
]

AIOHTTP_23 = aiohttp.__version__ > "2.3"

logger = logging.getLogger("aiotg")


class Bot:
    """Telegram bot framework designed for asyncio

    :param str api_token: Telegram bot token, ask @BotFather for this
    :param int api_timeout: Timeout for long polling
    :param str chatbase_token: Token for http://chatbase.com
    :param str name: Bot name
    :param callable json_serialize: JSON serializer function. (json.dumps by default)
    :param callable json_deserialize: JSON deserializer function. (json.loads by default)
    :param bool default_in_groups: Enables default callback in groups
    :param str proxy: Proxy URL to use for HTTP requests
    """

    _running = False
    _offset = 0

    def __init__(self,
                 api_token,
                 state,
                 api_timeout=API_TIMEOUT,
                 chatbase_token=None,
                 name=None,
                 json_serialize=json.dumps,
                 json_deserialize=json.loads,
                 default_in_groups=False,
                 proxy=None,
                 loop=None):
        self.api_token = api_token
        self.api_timeout = api_timeout
        self.chatbase_token = chatbase_token
        self.name = name
        self.json_serialize = json_serialize
        self.json_deserialize = json_deserialize
        self.default_in_groups = default_in_groups
        self.webhook_url = None
        self._session = None
        self.proxy = proxy
        self._loop = loop or asyncio.get_event_loop()

        self._proxy_is_socks = self.proxy and self.proxy.startswith("socks")
        if self._proxy_is_socks and "@" in self.proxy:
            proxy_scheme, proxy_loc = self.proxy.split("://", 1)
            proxy_auth, proxy_loc = splituser(proxy_loc)
            proxy_user, proxy_pass = splitpasswd(proxy_auth)
            if proxy_scheme == "socks5":
                proxy_auth_factory = Socks5Auth
            elif proxy_scheme == "socks4":
                proxy_auth_factory = Socks4Auth
            else:
                raise ValueError(
                    "Unknown SOCKS-proxy scheme: {}".format(proxy_scheme))
            self.proxy_auth = proxy_auth_factory(
                proxy_user, password=proxy_pass)
            self.proxy = "{}://{}".format(proxy_scheme, proxy_loc)
        else:
            self.proxy_auth = None

        def no_handle(mt):
            return lambda chat, msg: logger.debug("no handle for %s", mt)

        # Init default handlers and callbacks
        self.on_message = lambda x: None
        self._handlers = {mt: no_handle(mt) for mt in MESSAGE_TYPES}
        self._commands = []
        self._callbacks = []
        self._once = {}
        self._state = dict()
        self._chats = dict()
        # self._scripts =
        self._inlines = []
        self._checkouts = []
        self._default = lambda chat, message: None
        self._default_callback = lambda chat, cq: None
        self._default_inline = lambda iq: None

    async def loop(self):
        """
        Return bot's main loop as coroutine. Use with asyncio.

        :Example:

        >>> loop = asyncio.get_event_loop()
        >>> loop.run_until_complete(bot.loop())

        or

        >>> loop = asyncio.get_event_loop()
        >>> loop.create_task(bot.loop())
        """
        self._running = True
        while self._running:
            updates = await self.api_call(
                "getUpdates",
                offset=self._offset + 1,
                timeout=self.api_timeout)
            self._process_updates(updates)

    def run(self, debug=False, reload=None):
        """
        Convenience method for running bots in getUpdates mode

        :param bool debug: Enable debug logging and automatic reloading
        :param bool reload: Automatically reload bot on code change
        :Example:

        >>> if __name__ == '__main__':
        >>>     bot.run()

        """

        logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

        if reload is None:
            reload = debug

        bot_loop = asyncio.ensure_future(self.loop())

        try:
            if reload:
                self._loop.run_until_complete(
                    run_with_reloader(self._loop, bot_loop, self.stop))

            else:
                self._loop.run_until_complete(bot_loop)

        # User cancels
        except KeyboardInterrupt:
            logger.debug("User cancelled")
            bot_loop.cancel()
            self.stop()

        # Stop loop
        finally:
            if AIOHTTP_23:
                self._loop.run_until_complete(self.session.close())

            logger.debug("Closing loop")
            self._loop.stop()
            self._loop.close()

    def run_webhook(self, webhook_url, **options):
        """
        Convenience method for running bots in webhook mode

        :Example:

        >>> if __name__ == '__main__':
        >>>     bot.run_webhook(webhook_url="https://yourserver.com/webhooktoken")

        Additional documentation on https://core.telegram.org/bots/api#setwebhook
        """
        self._loop.run_until_complete(self.set_webhook(webhook_url, **options))
        if webhook_url:
            url = urlparse(webhook_url)
            app = self.create_webhook_app(url.path, self._loop)
            host = os.environ.get("HOST", "0.0.0.0")
            port = int(os.environ.get("PORT", 0)) or url.port

            if AIOHTTP_23:
                app.on_cleanup.append(lambda _: self.session.close())

            web.run_app(app, host=host, port=port)
        else:
            self._loop.run_until_complete(self.session.close())

    def future(self):
        return self._loop.create_future()

    def stop_webhook(self):
        """
        Use to switch from Webhook to getUpdates mode
        """
        self.run_webhook(webhook_url="")

    def add_command(self, regexp, fn):
        """
        Manually register regexp based command
        """
        coro = self.prepare_async_handler(fn)
        self._commands.append((regexp, coro))

    def command(self, regexp):
        """
        Register a new command

        :param str regexp: Regular expression matching the command to register

        :Example:

        >>> @bot.command(r"/echo (.+)")
        >>> def echo(chat, match):
        >>>     return chat.reply(match.group(1))
        """

        def decorator(fn):
            self.add_command(regexp, fn)
            return fn

        return decorator

    def chat_once(self, chat, fn):
        """
        Once handle default cmd
        """
        self._once[chat.id] = fn

    def chat_once_off(self, chat):
        """
        Remove once default handler
        """
        self._once[chat.id].pop(chat.id, None)

    def private_state(self, chat):
        self._state[chat.id]

    def default(self, callback):
        """
        Set callback for default command that is called on unrecognized
        commands for 1-to-1 chats
        If default_in_groups option is True, callback is called in groups too

        :Example:

        >>> @bot.default
        >>> def echo(chat, message):
        >>>     return chat.reply(message["text"])
        """
        self._default = callback
        return callback

    def add_inline(self, regexp, fn):
        """
        Manually register regexp based callback
        """
        coro = self.prepare_async_handler(fn)
        self._inlines.append((regexp, coro))

    def inline(self, callback):
        """
        Set callback for inline queries

        :Example:

        >>> @bot.inline
        >>> def echo(iq):
        >>>     return iq.answer([
        >>>         {"type": "text", "title": "test", "id": "0"}
        >>>     ])

        >>> @bot.inline(r"myinline-(.+)")
        >>> def echo(chat, iq, match):
        >>>     return iq.answer([
        >>>         {"type": "text", "title": "test", "id": "0"}
        >>>     ])
        """
        if callable(callback):
            self._default_inline = callback
            return callback
        elif isinstance(callback, str):

            def decorator(fn):
                self.add_inline(callback, fn)
                return fn

            return decorator
        else:
            raise TypeError("str expected {} given".format(type(callback)))

    def add_callback(self, regexp, fn):
        """
        Manually register regexp based callback
        """
        coro = self.prepare_async_handler(fn)
        self._callbacks.append((regexp, coro))

    def callback(self, callback):
        """
        Set callback for callback queries

        :Example:

        >>> @bot.callback
        >>> def echo(chat, cq):
        >>>     return cq.answer()

        >>> @bot.callback(r"buttonclick-(.+)")
        >>> def echo(chat, cq, match):
        >>>     return chat.reply(match.group(1))
        """
        if callable(callback):
            self._default_callback = callback
            return callback
        elif isinstance(callback, str):

            def decorator(fn):
                self.add_callback(callback, fn)
                return fn

            return decorator
        else:
            raise TypeError("str expected {} given".format(type(callback)))

    def add_checkout(self, regexp, fn):
        """
        Manually register regexp based checkout handler
        """
        self._checkouts.append((regexp, fn))

    def checkout(self, callback):
        if callable(callback):
            self._default_checkout = callback
        elif isinstance(callback, str):

            def decorator(fn):
                self.add_checkout(callback, fn)
                return fn

            return decorator
        else:
            raise TypeError("str expected {} given".format(type(callback)))

    def handle(self, msg_type):
        """
        Set handler for specific message type

        :Example:

        >>> @bot.handle("audio")
        >>> def handle(chat, audio):
        >>>     pass
        """

        def wrap(callback):
            coro = self.prepare_async_handler(callback)
            self._handlers[msg_type] = coro
            return callback

        return wrap

    def remove_handler(self, msg_type):
        self._handlers.pop(msg_type, None)

    def channel(self, channel_name):
        """
        Construct a Chat object used to post to channel

        :param str channel_name: Channel name
        """
        return Chat(self, channel_name, "channel")

    def private(self, user_id):
        """
        Construct a Chat object used to post direct messages

        :param str user_id: User id
        """

        return self._attach_chat(Chat(self, user_id, "private"))

    def group(self, group_id):
        """
        Construct a Chat object used to post group messages

        :param str group_id: Group chat id
        """
        return Chat(self, group_id, "group")

    def api_call(self, method, **params):
        """
        Call Telegram API.

        See https://core.telegram.org/bots/api for reference.

        :param str method: Telegram API method
        :param params: Arguments for the method call
        """
        coro = self._api_call(method, **params)
        # Explicitly ensure that API call is executed
        return asyncio.ensure_future(coro)

    async def _api_call(self, method, **params):
        url = "{0}/bot{1}/{2}".format(API_URL, self.api_token, method)
        logger.debug("api_call %s, %s", method, params)

        response = await self.session.post(
            url, data=params, proxy=self.proxy, proxy_auth=self.proxy_auth)

        if response.status == 200:
            return await response.json(loads=self.json_deserialize)
        elif response.status in RETRY_CODES:
            logger.info(
                "Server returned %d, retrying in %d sec.",
                response.status,
                RETRY_TIMEOUT,
            )
            await response.release()
            await asyncio.sleep(RETRY_TIMEOUT)
            return await self.api_call(method, **params)
        else:
            if response.headers["content-type"] == "application/json":
                json_resp = await response.json(loads=self.json_deserialize)
                err_msg = json_resp["description"]
            else:
                err_msg = await response.read()
            logger.error(err_msg)
            raise BotApiError(err_msg, response=response)

    async def get_me(self):
        """
        Returns basic information about the bot
        (see https://core.telegram.org/bots/api#getme)
        """
        json_result = await self.api_call("getMe")
        return json_result["result"]

    async def leave_chat(self, chat_id):
        """
        Use this method for your bot to leave a group, supergroup or channel.
        Returns True on success.

        :param int chat_id: Unique identifier for the target chat \
            or username of the target supergroup or channel \
            (in the format @channelusername)
        """
        json_result = await self.api_call("leaveChat", chat_id=chat_id)
        return json_result["result"]

    def send_message(self, chat_id, text, **options):
        """
        Send a text message to chat

        :param int chat_id: ID of the chat to send the message to
        :param str text: Text to send
        :param options: Additional sendMessage options
            (see https://core.telegram.org/bots/api#sendmessage)
        """
        return self.api_call(
            "sendMessage", chat_id=chat_id, text=text, **options)

    def edit_message_text(self, chat_id, message_id, text, **options):
        """
        Edit a text message in a chat

        :param int chat_id: ID of the chat the message to edit is in
        :param int message_id: ID of the message to edit
        :param str text: Text to edit the message to
        :param options: Additional API options
        """
        return self.api_call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            **options)

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup,
                                  **options):
        """
        Edit a reply markup of message in a chat

        :param int chat_id: ID of the chat the message to edit is in
        :param int message_id: ID of the message to edit
        :param str reply_markup: New inline keyboard markup for the message
        :param options: Additional API options
        """
        return self.api_call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            **options)

    async def get_file(self, file_id):
        """
        Get basic information about a file and prepare it for downloading.

        :param int file_id: File identifier to get information about
        :return: File object (see https://core.telegram.org/bots/api#file)
        """
        json = await self.api_call("getFile", file_id=file_id)
        return json["result"]

    def download_file(self, file_path, range=None):
        """
        Download a file from Telegram servers
        """
        headers = {"range": range} if range else None
        url = "{0}/file/bot{1}/{2}".format(API_URL, self.api_token, file_path)
        print('getting', url)
        return self.session.get(
            url, headers=headers, proxy=self.proxy, proxy_auth=self.proxy_auth)

    def download_file2(self, path):
        url = f'https://api.telegram.org/file/bot{self.api_token}/{path}'
        return ClientSession().get(url)

    def get_user_profile_photos(self, user_id, **options):
        """
        Get a list of profile pictures for a user

        :param int user_id: Unique identifier of the target user
        :param options: Additional getUserProfilePhotos options (see
            https://core.telegram.org/bots/api#getuserprofilephotos)
        """
        return self.api_call(
            "getUserProfilePhotos", user_id=str(user_id), **options)

    def track(self, message, name="Message"):
        """
        Track message using http://chatbase.com
        Set chatbase_token to make it work
        """
        if self.chatbase_token:
            asyncio.ensure_future(self._track(message, name))

    def stop(self):
        self._running = False

    async def webhook_handle(self, request):
        """
        aiohttp.web handle for processing web hooks

        :Example:

        >>> from aiohttp import web
        >>> app = web.Application()
        >>> app.router.add_route('/webhook')
        """
        update = await request.json(loads=self.json_deserialize)
        self._process_update(update)
        return web.Response()

    def create_webhook_app(self, path, loop=None):
        """
        Shorthand for creating aiohttp.web.Application with registered webhook hanlde
        """
        app = web.Application(loop=loop)
        app.router.add_route("POST", path, self.webhook_handle)
        return app

    def set_webhook(self, webhook_url, **options):
        """
        Register you webhook url for Telegram service.
        """
        return self.api_call("setWebhook", url=webhook_url, **options)

    def delete_webhook(self):
        """
        Tell Telegram to switch back to getUpdates mode
        """
        return self.api_call("deleteWebhook")

    @property
    def session(self):
        if not self._session or self._session.closed:
            kwargs = {"json_serialize": self.json_serialize}
            if self._proxy_is_socks:
                kwargs["connector"] = socks_connector.ProxyConnector()
                kwargs["request_class"] = socks_connector.ProxyClientRequest
            elif certifi:
                context = ssl.create_default_context(cafile=certifi.where())
                kwargs["connector"] = aiohttp.TCPConnector(ssl_context=context)

            self._session = aiohttp.ClientSession(**kwargs)
        return self._session

    def __del__(self):
        try:
            if not AIOHTTP_23 and self._session:
                self._session.close()
        except Exception as e:
            logger.debug(e)

    async def _track(self, message, name):
        response = await self.session.post(
            CHATBASE_URL,
            data=self.json_serialize({
                "api_key": self.chatbase_token,
                "type": "user",
                "message": message["text"],
                "platform": "telegram",
                "user_id": message["from"]["id"],
                "version": "1.0",
                "not_handled": "true",
            }),
        )
        if response.status != 200:
            logger.info("error submiting stats %d", response.status)
        await response.release()

    def _attach_chat(self, chat):
        self._chats[str(chat.id)] = chat
        print('chat attached', chat, chat.id)
        return chat
    
    def _get_chat(self, id):
        if not id:
            return
        return self._chats.get(str(id))

    def get_chat(self, id):
        return self._get_chat(id)


    def get_or_create_chat_state(self, message):
        """
        """

        chat_data = message['chat']
        chat = None

        if chat_data['type'] == 'private':
            chat = self._get_chat(chat_data.get('id'))

        if not chat:
            chat = Chat.from_message(self, message)

        # Adding chat to the state
        if chat.is_private():
            self._attach_chat(chat)
        return chat

    @classmethod
    def prepare_async_handler(cls, coro):
        """
        If it generator then wraps it in coro
        """
        if isinstance(coro, AsyncGeneratorType):
            return cls.play(coro)
        return coro

    def _process_message(self, message):
        """
        """

        chat = self.get_or_create_chat_state(message)
        
        if self.on_message:
            self.on_message(chat)
        
        #Chat specific waiters
        for mt in list(chat.handlers.keys()):
            if mt in message:
                chat.resolve_future(chat.handlers.pop(mt), message)
                return

        for mt, func in self._handlers.items():
            if mt in message:
                self.track(message, mt)
                coro = func(chat, message[mt])
                # if isinstance(func, AsyncGeneratorType):
                #     return self.play(chat, coro)
                return coro


        if "text" not in message:
            return

        for patterns, handler in self._commands:
            m = re.search(patterns, message["text"], re.I)
            if m:
                self.track(message, handler.__name__)
                coro = handler(chat, m)
                return coro

        if chat.is_waiting():
            chat.resolve_wait(message['text'])
            return

        # No match, run default if it's a 1to1 chat
        # However, if default_in_groups option is active, run default in any chat (not only 1to1)
        if not chat.is_group() or self.default_in_groups:
            # TODO: remove this once handler that used for actions chanining 
            once_handler = self._once.pop(chat.id, None)
            if once_handler:
                return once_handler(chat, message)
            self.track(message, "default")
            return self._default(chat, message)

    def _process_inline_query(self, query):
        iq = InlineQuery(self, query)

        for patterns, handler in self._inlines:
            match = re.search(patterns, query["query"], re.I)
            if match:
                return handler(iq, match)
        return self._default_inline(iq)

    def _process_callback_query(self, query):

        chat = self.get_or_create_chat_state(query["message"]) if "message" in query else None
        cq = CallbackQuery(self, query)

        # waiting callback response chat
        wait_cb_pattern = chat.get_callback_pattern()
        if wait_cb_pattern:
            match = re.search(wait_cb_pattern, cq.data, re.I)
            if match:
                cq.set_match(match)
                chat.resolve_callback(cq)
                return

        for patterns, handler in self._callbacks:
            match = re.search(patterns, cq.data, re.I)
            if match:
                cq.set_match(match)
                return handler(chat, cq, match)

        if chat and not chat.is_group() or self.default_in_groups:
            return self._default_callback(chat, cq)

    def _process_pre_checkout_query(self, query):
        pcq = PreCheckoutQuery(self, query)

        for patterns, handler in self._checkouts:
            match = re.search(patterns, pcq.invoice_payload, re.I)
            if match:
                return handler(pcq, match)
        return self._default_checkout(pcq)

    def _process_updates(self, updates):
        if not updates["ok"]:
            logger.error("getUpdates error: %s", updates.get("description"))
            return

        for update in updates["result"]:
            self._process_update(update)

    def _process_update(self, update):
        logger.debug("update %s", update)

        # Update offset
        self._offset = max(self._offset, update["update_id"])

        coro = None

        # Determine update type starting with message updates
        for ut in MESSAGE_UPDATES:
            if ut in update:
                coro = self._process_message(update[ut])
                break
        else:
            if "inline_query" in update:
                coro = self._process_inline_query(update["inline_query"])
            elif "callback_query" in update:
                coro = self._process_callback_query(update["callback_query"])
            elif "pre_checkout_query" in update:
                coro = self._process_pre_checkout_query(
                    update["pre_checkout_query"])
            else:
                logger.error("don't know how to handle update: %s", update)
        if coro:
            asyncio.ensure_future(coro)

    @staticmethod
    async def play_gen(chat, agen):
        nextval = None
        nexterr = None
        while True:
            await asyncio.sleep(0.05)
            try:
                if nexterr:
                    item = await agen.athrow(nexterr)
                else:
                    item = await agen.asend(nextval)
                nextval = None
                nexterr = None
                if isinstance(item, Exception):
                    logger.error('play generate exception %s', item)
                    raise item
                elif asyncio.isfuture(item):
                    nextval = await item
                elif isinstance(item, CoroutineType):
                    nextval = await item
                elif isinstance(item, str):
                    await chat.send_text(item)
            except GeneratorExit:
                logger.warn('generator exit')
                break
            except StopChatContext as ex:
                if ex.message:
                    await chat.send_message(ex.message)
                break
            except StopAsyncIteration:
                logger.info('asyncio stop iterator xx')
                break
            except asyncio.CancelledError:
                logger.warning('asyncio cancelled')
                break
            except BotApiError as ex:
                logger.exception('bot api error catched')
                nexterr = ex
            except Exception as ex:
                logger.exception('not matched ex')
                nexterr = ex
                break

    
    @classmethod
    def play(cls, agen):
        def wrapper(chat, *args, **kwargs):
            gen_or_coro = agen(chat, *args, **kwargs)
            if isinstance(gen_or_coro, AsyncGeneratorType):
                return cls.play_gen(chat, gen_or_coro)
            return gen_or_coro
        return wrapper


    


class InlineQuery:
    """
    Incoming inline query
    See https://core.telegram.org/bots/api#inline-mode for details
    """

    def __init__(self, bot, src):
        self.bot = bot
        self.sender = Sender(src["from"])
        self.query_id = src["id"]
        self.query = src["query"]

    def answer(self, results, **options):
        return self.bot.api_call(
            "answerInlineQuery",
            inline_query_id=self.query_id,
            results=self.bot.json_serialize(results),
            **options)


class TgInlineQuery(InlineQuery):
    def __init__(self, *args, **kwargs):
        logger.warning("TgInlineQuery is depricated, use InlineQuery instead")
        super().__init__(*args, **kwargs)


class CallbackQuery:
    def __init__(self, bot, src):
        self.bot = bot
        self.query_id = src["id"]
        self.data = src["data"]
        self.src = src
        self.match = None

    def answer(self, **options):
        return self.bot.api_call(
            "answerCallbackQuery", callback_query_id=self.query_id, **options)

    def set_match(self, match):
        self.match = match


class Button(dict):
    def __init__(self, text, callback_data, **kwargs):
        self.cbprefix = kwargs.get('cbprefix', '')
        super().__init__(text=text, callback_data=self.cbprefix + callback_data, **kwargs)

    def set_cbprefix(self, cbprefix):
        self.cbprefix = cbprefix


class Row(list):
    def __init__(self, *args, **kwargs):
        self.attached = False
        self.cbprefix = kwargs.get('cbprefix', '')
        if len(args):
            for item in args:
                self.append(item)

    def set_cbprefix(self, cbprefix):
        self.cbprefix = cbprefix

    def attach(self):
        self.attached = True


class Keyboard(dict):
    def __init__(self, *rows, **kwargs):
        super().__init__(**kwargs)
        self['keyboard'] = [*(rows or [])]
        self.new_row()
        
    def new_row(self):
        self.row = Row()

    def add_btn(self, btn):
        self.row.append(btn)
        if not self.row.attached:
            self.row.attach()
            self['keyboard'].append(self.row)


class InlineKeyboard(dict):
    def __init__(self, *rows):
        self['inline_keyboard'] = [*(rows or [])]
        self.new_row()
        
    def new_row(self):
        self.row = Row()

    def add_btn(self, btn):
        self.row.append(btn)
        if not self.row.attached:
            self.row.attach()
            self['inline_keyboard'].append(self.row)


class PreCheckoutQuery:
    def __init__(self, bot, src):
        self.bot = bot
        self.sender = Sender(src["from"])
        self.query_id = src["id"]
        self.currency = src["currency"]
        self.total_amount = src["total_amount"]
        self.invoice_payload = src["invoice_payload"]

    def answer(self, error_message=None, **options):
        return self.bot.api_call(
            "answerPreCheckoutQuery",
            pre_checkout_query_id=self.query_id,
            ok=error_message is None,
            error_message=error_message,
            **options)


class BotApiError(RuntimeError):
    def __init__(self, *args, response):
        super().__init__(*args)
        self.response = response


