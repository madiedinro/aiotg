import asyncio
import logging


logger = logging.getLogger("aiotg")



class StopChatContext(StopAsyncIteration):
    def __init__(self, message):
        self.message = message


class Chat:
    """
    Wrapper for telegram chats, passed to most callbacks
    """

    def send_text(self, text, **options):
        """
        Send a text message to the chat.

        :param str text: Text of the message to send
        :param options: Additional sendMessage options (see
            https://core.telegram.org/bots/api#sendmessage
        """
        return self.bot.send_message(self.id, text, **options)

    def send_message(self, text, markup=None, parse_mode=None):

        if markup is None:
            markup = {}
        return self.send_text(
            text,
            reply_markup=self.bot.json_serialize(markup),
            parse_mode=parse_mode,
        )

    def reply(self, text, markup=None, parse_mode=None):
        """
        Reply to the message this `Chat` object is based on.

        :param str text: Text of the message to send
        :param dict markup: Markup options
        :param str parse_mode: Text parsing mode (``"Markdown"``, ``"HTML"`` or
            ``None``)
        """
        if markup is None:
            markup = {}

        return self.send_text(
            text,
            reply_to_message_id=self.message["message_id"],
            disable_web_page_preview="true",
            reply_markup=self.bot.json_serialize(markup),
            parse_mode=parse_mode,
        )

    def edit_text(self, message_id, text, markup=None, parse_mode=None):
        """
        Edit the message in this chat.

        :param int message_id: ID of the message to edit
        :param str text: Text to edit the message to
        :param dict markup: Markup options
        :param str parse_mode: Text parsing mode (``"Markdown"``, ``"HTML"`` or
            ``None``)
        """
        if markup is None:
            markup = {}

        return self.bot.edit_message_text(
            self.id,
            message_id,
            text,
            reply_markup=self.bot.json_serialize(markup),
            parse_mode=parse_mode,
        )

    def edit_reply_markup(self, message_id, markup):
        """
        Edit only reply markup of the message in this chat.

        :param int message_id: ID of the message to edit
        :param dict markup: Markup options
        """
        return self.bot.edit_message_reply_markup(
            self.id, message_id, reply_markup=self.bot.json_serialize(markup)
        )

    def get_chat(self):
        """
        Get information about the chat.
        """
        return self.bot.api_call("getChat", chat_id=str(self.id))

    def get_chat_administrators(self):
        """
        Get a list of administrators in a chat. Chat must not be private.
        """
        return self.bot.api_call("getChatAdministrators", chat_id=str(self.id))

    def get_chat_members_count(self):
        """
        Get the number of members in a chat.
        """
        return self.bot.api_call("getChatMembersCount", chat_id=str(self.id))

    def get_chat_member(self, user_id):
        """
        Get information about a member of a chat.

        :param int user_id: Unique identifier of the target user
        """
        return self.bot.api_call(
            "getChatMember", chat_id=str(self.id), user_id=str(user_id)
        )

    def send_sticker(self, sticker, **options):
        """
        Send a sticker to the chat.

        :param sticker: Sticker to send (file or string)
        :param options: Additional sendSticker options (see
            https://core.telegram.org/bots/api#sendsticker)
        """
        return self.bot.api_call(
            "sendSticker", chat_id=str(self.id), sticker=sticker, **options
        )

    def send_audio(self, audio, **options):
        """
        Send an mp3 audio file to the chat.

        :param audio: Object containing the audio data
        :param options: Additional sendAudio options (see
            https://core.telegram.org/bots/api#sendaudio)

        :Example:

        >>> with open("foo.mp3", "rb") as f:
        >>>     await chat.send_audio(f, performer="Foo", title="Eversong")
        """
        return self.bot.api_call(
            "sendAudio", chat_id=str(self.id), audio=audio, **options
        )

    def send_photo(self, photo, caption="", **options):
        """
        Send a photo to the chat.

        :param photo: Object containing the photo data
        :param str caption: Photo caption (optional)
        :param options: Additional sendPhoto options (see
            https://core.telegram.org/bots/api#sendphoto)

        :Example:

        >>> with open("foo.png", "rb") as f:
        >>>     await chat.send_photo(f, caption="Would you look at this!")
        """
        return self.bot.api_call(
            "sendPhoto", chat_id=str(self.id), photo=photo, caption=caption, **options
        )

    def send_video(self, video, caption="", **options):
        """
        Send an mp4 video file to the chat.

        :param video: Object containing the video data
        :param str caption: Video caption (optional)
        :param options: Additional sendVideo options (see
            https://core.telegram.org/bots/api#sendvideo)

        :Example:

        >>> with open("foo.mp4", "rb") as f:
        >>>     await chat.send_video(f)
        """
        return self.bot.api_call(
            "sendVideo", chat_id=str(self.id), video=video, caption=caption, **options
        )

    def send_document(self, document, caption="", **options):
        """
        Send a general file.

        :param document: Object containing the document data
        :param str caption: Document caption (optional)
        :param options: Additional sendDocument options (see
            https://core.telegram.org/bots/api#senddocument)

        :Example:

        >>> with open("file.doc", "rb") as f:
        >>>     await chat.send_document(f)
        """
        return self.bot.api_call(
            "sendDocument",
            chat_id=str(self.id),
            document=document,
            caption=caption,
            **options
        )

    def send_voice(self, voice, **options):
        """
        Send an OPUS-encoded .ogg audio file.

        :param voice: Object containing the audio data
        :param options: Additional sendVoice options (see
            https://core.telegram.org/bots/api#sendvoice)

        :Example:

        >>> with open("voice.ogg", "rb") as f:
        >>>     await chat.send_voice(f)
        """
        return self.bot.api_call(
            "sendVoice", chat_id=str(self.id), voice=voice, **options
        )

    def send_location(self, latitude, longitude, **options):
        """
        Send a point on the map.

        :param float latitude: Latitude of the location
        :param float longitude: Longitude of the location
        :param options: Additional sendLocation options (see
            https://core.telegram.org/bots/api#sendlocation)
        """
        return self.bot.api_call(
            "sendLocation",
            chat_id=self.id,
            latitude=latitude,
            longitude=longitude,
            **options
        )

    def send_venue(self, latitude, longitude, title, address, **options):
        """
        Send information about a venue.

        :param float latitude: Latitude of the location
        :param float longitude: Longitude of the location
        :param str title: Name of the venue
        :param str address: Address of the venue
        :param options: Additional sendVenue options (see
            https://core.telegram.org/bots/api#sendvenue)
        """
        return self.bot.api_call(
            "sendVenue",
            chat_id=self.id,
            latitude=latitude,
            longitude=longitude,
            title=title,
            address=address,
            **options
        )

    def send_contact(self, phone_number, first_name, **options):
        """
        Send phone contacts.

        :param str phone_number: Contact's phone number
        :param str first_name: Contact's first name
        :param options: Additional sendContact options (see
            https://core.telegram.org/bots/api#sendcontact)
        """
        return self.bot.api_call(
            "sendContact",
            chat_id=self.id,
            phone_number=phone_number,
            first_name=first_name,
            **options
        )

    def send_chat_action(self, action):
        """
        Send a chat action, to tell the user that something is happening on the
        bot's side.

        Available actions:

        *  `typing` for text messages
        *  `upload_photo` for photos
        *  `record_video` and `upload_video` for videos
        *  `record_audio` and `upload_audio` for audio files
        *  `upload_document` for general files
        *  `find_location` for location data

        :param str action: Type of action to broadcast
        """
        return self.bot.api_call("sendChatAction", chat_id=self.id, action=action)

    def send_media_group(
        self,
        media: str,
        disable_notification: bool = False,
        reply_to_message_id: int = None,
        **options
    ):
        """
        Send a group of photos or videos as an album

        :param media: A JSON-serialized array describing photos and videos
        to be sent, must include 2–10 items
        :param disable_notification: Sends the messages silently. Users will
        receive a notification with no sound.
        :param reply_to_message_id: If the messages are a reply, ID of the original message
        :param options: Additional sendMediaGroup options (see
        https://core.telegram.org/bots/api#sendmediagroup)

        :Example:
        >>> from json import dumps
        >>> photos_urls = [
        >>>     "https://telegram.org/img/t_logo.png",
        >>>     "https://telegram.org/img/SiteAndroid.jpg?1",
        >>>     "https://telegram.org/img/SiteiOs.jpg?1",
        >>>     "https://telegram.org/img/SiteWP.jpg?2"
        >>> ]
        >>> tg_album = []
        >>> count = len(photos_urls)
        >>> for i, p in enumerate(photos_urls):
        >>> {
        >>>     'type': 'photo',
        >>>     'media': p,
        >>>     'caption': f'{i} of {count}'
        >>> }
        >>> await chat.send_media_group(dumps(tg_album))
        """

        return self.bot.api_call(
            "sendMediaGroup",
            chat_id=str(self.id),
            media=media,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            **options
        )

    def forward_message(self, from_chat_id, message_id):
        """
        Forward a message from another chat to this chat.

        :param int from_chat_id: ID of the chat to forward the message from
        :param int message_id: ID of the message to forward
        """
        return self.bot.api_call(
            "forwardMessage",
            chat_id=self.id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )

    def kick_chat_member(self, user_id):
        """
        Use this method to kick a user from a group or a supergroup.
        The bot must be an administrator in the group for this to work.

        :param int user_id: Unique identifier of the target user
        """
        return self.bot.api_call("kickChatMember", chat_id=self.id, user_id=user_id)

    def unban_chat_member(self, user_id):
        """
        Use this method to unban a previously kicked user in a supergroup.
        The bot must be an administrator in the group for this to work.

        :param int user_id: Unique identifier of the target user
        """
        return self.bot.api_call("unbanChatMember", chat_id=self.id, user_id=user_id)

    def delete_message(self, message_id):
        """
        Delete message from this chat

        :param int message_id: ID of the message
        """
        return self.bot.api_call(
            "deleteMessage", chat_id=self.id, message_id=message_id
        )

    def is_private(self):
        return self.type == 'private'

    def is_group(self):
        """
        Check if this chat is a group.

        :return: ``True`` if this chat is a group, ``False`` otherwise
        """
        return self.type == "group" or self.type == "supergroup"

    def once(self, fn):
        """
        Handle next message in chat with handler once

        :param str name: Name of the chat stage
        """
        self.bot.chat_once(self, fn)

    def off(self):
        """

        """
        self.bot.chat_once_off(self)

    def is_waiting(self):
        return self.future != None

    def get_callback_pattern(self):
        if self.future_cb and self.callback_pattern:
            return self.callback_pattern

    def wait_callback(self, pattern):
        self.future_cb = self.bot.future()
        self.callback_pattern = pattern
        return self.future_cb

    def wait_message(self):
        self.future = self.bot.future()
        return self.future

    def resolve_wait(self, message):
        future = self.future
        self.future = None
        future.set_result(message)

    def resolve_callback(self, query):
        self.callback_pattern = None
        future = self.future_cb
        self.future_cb = None
        future.set_result(query)

    def break_play(self):
        if self.future:
            self.future.set_exception(asyncio.CancelledError)
        self.future = None

    def stop_play(self, message):
        return StopChatContext(message)

    def register_context(self, instance):
        self.contexts.insert(0, instance)
    
    def remove_context(self, instance):
        self.contexts.remove(instance)

    def new_context(self):
        return AsyncChatContext(self)

    def __init__(self, bot, chat_id, chat_type="private", src_message=None):
        self.bot = bot
        self.message = src_message
        self.future = None
        self.future_cb = None
        self.callback_pattern = None
        self.contexts = []
        
        if src_message and "from" in src_message:
            sender = src_message["from"]
        else:
            sender = {"first_name": "N/A"}
        self.sender = Sender(sender)
        self.id = chat_id
        self.type = chat_type

    @staticmethod
    def from_message(bot, message):
        """
        Create a ``Chat`` object from a message.

        :param Bot bot: ``Bot`` object the message and chat belong to
        :param dict message: Message to base the object on
        :return: A chat object based on the message
        """
        chat = message["chat"]
        return Chat(bot, chat["id"], chat["type"], message)


class Sender(dict):
    """A small wrapper for sender info, mostly used for logging"""

    def __repr__(self):
        uname = " (%s)" % self["username"] if "username" in self else ""
        return self["first_name"] + uname


class AsyncChatContext:
    def __init__(self, chat: Chat):
        self.chat = chat

    async def __aenter__(self):
        print('registring context')
        self.chat.register_context(self)

    async def __aexit__(self, exc_type, exc, tb):
        print('removing context')
        self.chat.remove_context(self)
