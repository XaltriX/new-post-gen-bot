from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
                          ContextTypes, filters, ConversationHandler)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.request import HTTPXRequest
from telegram.error import TelegramError
from io import BytesIO
from PIL import Image
import html
import logging
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId
import pytz
import asyncio

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB Configuration
MONGO_URI = "mongodb+srv://Infinitymovies:rockstaryohan@filterbot.c43yufi.mongodb.net/?retryWrites=true&w=majority&appName=Filterbot"
DB_NAME = "channel_post_bot"

# MongoDB Client with better connection settings
mongo_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    maxPoolSize=50
)
db = mongo_client[DB_NAME]
channels_collection = db['channels']
posts_collection = db['scheduled_posts']
users_collection = db['users']

# States for conversation
THUMBNAIL, VIDEO_LINK, HOW_TO_OPEN, SELECT_POSTING_TYPE, SELECT_CHANNELS, SCHEDULE_TIME, ADD_CHANNEL_TYPE, ADD_CHANNEL_DATA = range(8)

# Permanent thumbnail size
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# Bot token
BOT_TOKEN = "7008031473:AAH-ZLZXr5vM2X_0rdMcdSRsfRwG6zzqvYE"

# Indian timezone
IST = pytz.timezone('Asia/Kolkata')

def init_db():
    """Initialize database with proper indexes"""
    try:
        channels_collection.create_index([("user_id", 1)])
        channels_collection.create_index([("channel_id", 1)])
        channels_collection.create_index([("user_id", 1), ("channel_id", 1)], unique=True)
        posts_collection.create_index([("user_id", 1)])
        posts_collection.create_index([("scheduled_time", 1)])
        posts_collection.create_index([("status", 1)])
        posts_collection.create_index([("status", 1), ("scheduled_time", 1)])
        users_collection.create_index([("user_id", 1)], unique=True)
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")

async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, channel_id: str):
    """Check if bot is admin in channel"""
    try:
        bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
        return bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking admin status for {channel_id}: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_data = context.user_data
    user_data.clear()
    user_id = update.effective_user.id
    
    # Store user info
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "username": update.effective_user.username,
            "first_name": update.effective_user.first_name,
            "last_seen": datetime.now(IST)
        }},
        upsert=True
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Create New Post", callback_data="create_post")],
        [InlineKeyboardButton("📺 Manage Channels", callback_data="manage_channels")],
        [InlineKeyboardButton("📊 View Scheduled Posts", callback_data="view_scheduled")],
        [InlineKeyboardButton("📜 Posted History", callback_data="view_history")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🎬 *Welcome to Advanced Channel Post Generator Bot!*\n\n"
        "✨ Features:\n"
        "• Create beautiful channel posts\n"
        "• Post immediately or schedule\n"
        "• Manage multiple channels\n"
        "• Auto-posting with IST timezone\n"
        "• View scheduled & posted history\n\n"
        "👇 Choose an option below:"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def create_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start post creation flow"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("⏭️ Skip Thumbnail", callback_data="skip_thumbnail")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎨 *Create New Post*\n\n"
        "📸 *Step 1:* Send me the thumbnail (Photo/Video/GIF)\n"
        "or click Skip if you don't want to add one.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return THUMBNAIL

async def resize_media(file_bytes, is_photo=True):
    """Resize media to standard dimensions"""
    try:
        image = Image.open(BytesIO(file_bytes))
        
        # Convert to RGB
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize maintaining aspect ratio
        image.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)
        
        # Create final image with black background
        final_image = Image.new('RGB', (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (0, 0, 0))
        x = (THUMBNAIL_WIDTH - image.width) // 2
        y = (THUMBNAIL_HEIGHT - image.height) // 2
        final_image.paste(image, (x, y))
        
        # Save to BytesIO
        output = BytesIO()
        final_image.save(output, format='JPEG', quality=95)
        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error resizing media: {e}")
        return None

async def receive_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process thumbnail"""
    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            file_bytes = await file.download_as_bytearray()
            resized = await resize_media(bytes(file_bytes), is_photo=True)
            
            if resized:
                context.user_data['thumbnail'] = resized
                context.user_data['thumbnail_type'] = 'photo'
            else:
                context.user_data['thumbnail'] = photo.file_id
                context.user_data['thumbnail_type'] = 'photo'
                
        elif update.message.video:
            video = update.message.video
            context.user_data['thumbnail'] = video.file_id
            context.user_data['thumbnail_type'] = 'video'
            
        elif update.message.animation:
            animation = update.message.animation
            context.user_data['thumbnail'] = animation.file_id
            context.user_data['thumbnail_type'] = 'animation'
        else:
            await update.message.reply_text("❌ Please send a Photo, Video, or GIF, or use the Skip button.")
            return THUMBNAIL
        
        await update.message.reply_text(
            "✅ Thumbnail saved!\n\n"
            "🔗 *Step 2:* Now send me the video link (URL)",
            parse_mode=ParseMode.MARKDOWN
        )
        return VIDEO_LINK
        
    except Exception as e:
        logger.error(f"Error receiving thumbnail: {e}")
        await update.message.reply_text(f"❌ Error processing media. Please try again or skip.")
        return THUMBNAIL

async def skip_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip thumbnail step"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⏭️ Thumbnail skipped!\n\n"
        "🔗 *Step 2:* Send me the video link (URL)",
        parse_mode=ParseMode.MARKDOWN
    )
    return VIDEO_LINK

async def receive_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive video link"""
    video_link = update.message.text.strip()
    
    if not (video_link.startswith('http://') or video_link.startswith('https://')):
        await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://"
        )
        return VIDEO_LINK
    
    context.user_data['video_link'] = video_link
    
    keyboard = [[InlineKeyboardButton("⏭️ Skip Instructions", callback_data="skip_instructions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✅ Video link saved!\n\n"
        "📋 *Step 3:* Send me the 'How to Open' link/instructions\n"
        "(This will appear as clickable text in the post)\n"
        "or click Skip if not needed.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return HOW_TO_OPEN

async def receive_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive instructions"""
    instructions_link = update.message.text.strip()
    
    if instructions_link.startswith('http://') or instructions_link.startswith('https://'):
        context.user_data['instructions_link'] = instructions_link
    else:
        context.user_data['instructions_text'] = instructions_link
    
    await ask_posting_type(update, context)
    return SELECT_POSTING_TYPE

async def skip_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip instructions step"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("⏭️ Instructions skipped!")
    await ask_posting_type(update, context, from_callback=True)
    return SELECT_POSTING_TYPE

async def ask_posting_type(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    """Ask user for posting type"""
    keyboard = [
        [InlineKeyboardButton("📤 Post Now", callback_data="post_now")],
        [InlineKeyboardButton("⏰ Schedule Post", callback_data="schedule_post")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        "✅ *Post content ready!*\n\n"
        "📌 *Step 4:* Choose posting option:\n\n"
        "• *Post Now:* Publish immediately\n"
        "• *Schedule Post:* Set future date & time (IST)"
    )
    
    if from_callback:
        await update.callback_query.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_posting_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle posting type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "post_now":
        context.user_data['posting_type'] = 'immediate'
        await show_channel_selection(update, context)
        return SELECT_CHANNELS
        
    elif query.data == "schedule_post":
        context.user_data['posting_type'] = 'scheduled'
        await ask_schedule_time(update, context)
        return SCHEDULE_TIME
        
    elif query.data == "back_to_menu":
        await show_main_menu(update, context, from_callback=True)
        return ConversationHandler.END

async def ask_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for schedule time"""
    query = update.callback_query
    now_ist = datetime.now(IST)
    
    keyboard = []
    for hours in [1, 2, 4, 8, 12, 24]:
        future_time = now_ist + timedelta(hours=hours)
        time_str = future_time.strftime("%I:%M %p, %d %b")
        keyboard.append([InlineKeyboardButton(
            f"⏰ {time_str} ({hours}h)", 
            callback_data=f"quick_time_{hours}"
        )])
    
    keyboard.append([InlineKeyboardButton("📅 Custom Date & Time", callback_data="custom_time")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_posting_type")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"⏰ *Schedule Your Post*\n\n"
        f"🕐 Current Time (IST): {now_ist.strftime('%I:%M %p, %d %b %Y')}\n\n"
        f"Choose a quick option or set custom time:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle schedule time selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("quick_time_"):
        hours = int(query.data.split("_")[2])
        scheduled_time = datetime.now(IST) + timedelta(hours=hours)
        context.user_data['scheduled_time'] = scheduled_time
        
        await query.edit_message_text(
            f"✅ *Scheduled for:*\n{scheduled_time.strftime('%I:%M %p, %d %B %Y')} (IST)",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await show_channel_selection(update, context, new_message=True)
        return SELECT_CHANNELS
        
    elif query.data == "custom_time":
        await query.edit_message_text(
            "📅 *Custom Schedule*\n\n"
            "Please send date and time in this format:\n"
            "`DD-MM-YYYY HH:MM`\n\n"
            "Example: `25-12-2024 18:30`\n"
            "(Time in IST - Indian Standard Time)\n\n"
            "Or send /cancel to go back",
            parse_mode=ParseMode.MARKDOWN
        )
        return SCHEDULE_TIME
        
    elif query.data == "back_to_posting_type":
        await ask_posting_type(update, context, from_callback=True)
        return SELECT_POSTING_TYPE

async def handle_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom time input"""
    time_str = update.message.text.strip()
    
    try:
        # Parse the datetime
        scheduled_time = datetime.strptime(time_str, "%d-%m-%Y %H:%M")
        scheduled_time = IST.localize(scheduled_time)
        
        # Check if time is in future
        now_ist = datetime.now(IST)
        if scheduled_time <= now_ist:
            await update.message.reply_text(
                "❌ Scheduled time must be in the future!\n\n"
                "Please send a valid date and time."
            )
            return SCHEDULE_TIME
        
        context.user_data['scheduled_time'] = scheduled_time
        
        await update.message.reply_text(
            f"✅ *Scheduled for:*\n{scheduled_time.strftime('%I:%M %p, %d %B %Y')} (IST)",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await show_channel_selection(update, context, new_message=True)
        return SELECT_CHANNELS
        
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format!\n\n"
            "Please use: `DD-MM-YYYY HH:MM`\n"
            "Example: `25-12-2024 18:30`",
            parse_mode=ParseMode.MARKDOWN
        )
        return SCHEDULE_TIME

async def show_channel_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, new_message=False):
    """Show channel selection interface"""
    user_id = update.effective_user.id
    channels = list(channels_collection.find({"user_id": user_id}))
    
    if not channels:
        keyboard = [
            [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = (
            "📺 *No Channels Added*\n\n"
            "You haven't added any channels yet.\n"
            "Please add a channel first to post."
        )
        
        if new_message or not update.callback_query:
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        return SELECT_CHANNELS
    
    if 'selected_channels' not in context.user_data:
        context.user_data['selected_channels'] = []
    
    keyboard = []
    
    # Show each channel with checkbox
    for channel in channels:
        channel_id = str(channel['_id'])
        is_selected = channel_id in context.user_data['selected_channels']
        checkbox = "✅" if is_selected else "☐"
        channel_name = channel.get('channel_name', channel['channel_id'])
        
        # Truncate long channel names
        if len(channel_name) > 30:
            channel_name = channel_name[:27] + "..."
        
        keyboard.append([InlineKeyboardButton(
            f"{checkbox} {channel_name}",
            callback_data=f"toggle_channel_{channel_id}"
        )])
    
    # Add select/deselect all button
    selected_count = len(context.user_data['selected_channels'])
    if selected_count == len(channels) and len(channels) > 0:
        keyboard.append([InlineKeyboardButton("❌ Deselect All", callback_data="deselect_all")])
    else:
        keyboard.append([InlineKeyboardButton("✅ Select All", callback_data="select_all")])
    
    keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel")])
    
    # Show confirm button only if at least one channel is selected
    if context.user_data['selected_channels']:
        keyboard.append([InlineKeyboardButton("✔️ Confirm & Post", callback_data="confirm_channels")])
    
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        f"📺 *Select Channels to Post*\n\n"
        f"Selected: *{selected_count}/{len(channels)}*\n\n"
        f"💡 Tap any channel to select/deselect:"
    )
    
    if new_message or not update.callback_query:
        if update.callback_query:
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        try:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            # If message is the same, just ignore
            logger.debug(f"Could not edit message: {e}")
            pass

async def handle_channel_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel selection callbacks"""
    query = update.callback_query
    
    user_id = update.effective_user.id
    
    if query.data.startswith("toggle_channel_"):
        # Answer callback immediately to show selection is registered
        await query.answer("Channel toggled ✓")
        
        # Extract channel ID - handle IDs that might contain underscores
        parts = query.data.split("_")
        if len(parts) >= 3:
            channel_id = "_".join(parts[2:])  # Join all parts after "toggle_channel_"
        else:
            logger.error(f"Invalid toggle_channel callback data: {query.data}")
            return SELECT_CHANNELS
        
        if 'selected_channels' not in context.user_data:
            context.user_data['selected_channels'] = []
        
        if channel_id in context.user_data['selected_channels']:
            context.user_data['selected_channels'].remove(channel_id)
        else:
            context.user_data['selected_channels'].append(channel_id)
        
        await show_channel_selection(update, context)
        return SELECT_CHANNELS
        
    elif query.data == "select_all":
        await query.answer("All channels selected ✓")
        channels = list(channels_collection.find({"user_id": user_id}))
        context.user_data['selected_channels'] = [str(ch['_id']) for ch in channels]
        await show_channel_selection(update, context)
        return SELECT_CHANNELS
        
    elif query.data == "deselect_all":
        await query.answer("All channels deselected")
        context.user_data['selected_channels'] = []
        await show_channel_selection(update, context)
        return SELECT_CHANNELS
        
    elif query.data == "add_channel":
        await query.answer()
        await start_add_channel(update, context)
        return ADD_CHANNEL_TYPE
        
    elif query.data == "confirm_channels":
        if not context.user_data.get('selected_channels'):
            await query.answer("⚠️ Please select at least one channel!", show_alert=True)
            return SELECT_CHANNELS
        await query.answer()
        await process_post(update, context)
        return ConversationHandler.END
    
    elif query.data == "back_to_menu":
        await query.answer()
        context.user_data.clear()  # Clear selection data
        await show_main_menu(update, context, from_callback=True)
        return ConversationHandler.END

async def process_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process and send/schedule the post"""
    query = update.callback_query
    user_data = context.user_data
    
    await query.edit_message_text("⏳ Processing your post...")
    
    selected_channel_ids = user_data.get('selected_channels', [])
    posting_type = user_data.get('posting_type', 'immediate')
    
    # Get channel details
    channels = []
    for ch_id in selected_channel_ids:
        try:
            channel = channels_collection.find_one({"_id": ObjectId(ch_id)})
            if channel:
                channels.append(channel)
        except Exception as e:
            logger.error(f"Error fetching channel {ch_id}: {e}")
    
    # Verify bot admin status
    valid_channels = []
    invalid_channels = []
    
    for channel in channels:
        is_admin = await is_bot_admin(context, channel['channel_id'])
        if is_admin:
            valid_channels.append(channel)
        else:
            invalid_channels.append(channel)
    
    if not valid_channels:
        await query.message.reply_text(
            "❌ *Error: Bot is not admin in any selected channel!*\n\n"
            "Please make sure the bot is added as an admin in your channels.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if invalid_channels:
        invalid_names = ", ".join([ch.get('channel_name', ch['channel_id']) for ch in invalid_channels])
        await query.message.reply_text(
            f"⚠️ *Warning:* Bot is not admin in:\n{invalid_names}\n\n"
            f"Proceeding with {len(valid_channels)} valid channel(s)...",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Generate post message
    post_message = generate_post_message(user_data)
    
    if posting_type == 'immediate':
        # Post immediately
        success_count = 0
        failed_channels = []
        
        for channel in valid_channels:
            try:
                await send_post_to_channel(context, channel['channel_id'], user_data, post_message)
                success_count += 1
                
                # Save to history
                posts_collection.insert_one({
                    "user_id": update.effective_user.id,
                    "channel_id": channel['channel_id'],
                    "channel_name": channel.get('channel_name', channel['channel_id']),
                    "post_data": {
                        'video_link': user_data.get('video_link'),
                        'instructions_link': user_data.get('instructions_link'),
                        'instructions_text': user_data.get('instructions_text'),
                        'thumbnail_type': user_data.get('thumbnail_type')
                    },
                    "status": "posted",
                    "posted_time": datetime.now(IST)
                })
                
            except Exception as e:
                logger.error(f"Error posting to {channel['channel_id']}: {e}")
                failed_channels.append(channel.get('channel_name', channel['channel_id']))
        
        result_text = f"✅ *Post sent to {success_count} channel(s)!*\n\n"
        if failed_channels:
            result_text += f"❌ Failed: {', '.join(failed_channels)}\n\n"
        result_text += "Use /start to create another post."
        
        await query.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        
    else:
        # Schedule post
        scheduled_time = user_data['scheduled_time']
        
        for channel in valid_channels:
            # Store thumbnail properly for scheduled posts
            thumbnail_data = None
            thumbnail_type = user_data.get('thumbnail_type')
            
            if 'thumbnail' in user_data:
                thumbnail = user_data['thumbnail']
                if isinstance(thumbnail, BytesIO):
                    # Convert BytesIO to bytes for storage
                    thumbnail.seek(0)
                    thumbnail_data = thumbnail.read()
                else:
                    # It's a file_id
                    thumbnail_data = thumbnail
            
            posts_collection.insert_one({
                "user_id": update.effective_user.id,
                "channel_id": channel['channel_id'],
                "channel_name": channel.get('channel_name', channel['channel_id']),
                "post_data": {
                    'video_link': user_data.get('video_link'),
                    'instructions_link': user_data.get('instructions_link'),
                    'instructions_text': user_data.get('instructions_text'),
                    'thumbnail': thumbnail_data,
                    'thumbnail_type': thumbnail_type
                },
                "status": "scheduled",
                "scheduled_time": scheduled_time,
                "created_at": datetime.now(IST)
            })
        
        await query.message.reply_text(
            f"✅ *Post scheduled successfully!*\n\n"
            f"📅 Date: {scheduled_time.strftime('%d %B %Y')}\n"
            f"⏰ Time: {scheduled_time.strftime('%I:%M %p')} IST\n"
            f"📺 Channels: {len(valid_channels)}\n\n"
            f"Use /start to view scheduled posts or create another.",
            parse_mode=ParseMode.MARKDOWN
        )

def generate_post_message(user_data):
    """Generate formatted post message"""
    video_link = user_data.get('video_link')
    instructions_link = user_data.get('instructions_link')
    instructions_text = user_data.get('instructions_text')
    
    video_link_escaped = html.escape(video_link)
    
    message = "╔══════════════════╗\n"
    message += "║ 🎥 𝑵𝑬𝑾 𝑽𝑰𝑫𝑬𝑶 𝑨𝑳𝑬𝑹𝑻 ║\n"
    message += "╚══════════════════╝\n"
    message += "┃\n"
    message += f'┣⊳ 📥 <a href="{video_link_escaped}">𝑫𝒐𝒘𝒏𝒍𝒐𝒂𝒅</a>\n'
    
    if instructions_link:
        instructions_link_escaped = html.escape(instructions_link)
        message += f'┣⊳ 🔗 <a href="{instructions_link_escaped}">𝑯𝒐𝒘 𝒕𝒐 𝑶𝒑𝒆𝒏</a>\n'
    elif instructions_text:
        instructions_text_escaped = html.escape(instructions_text)
        message += f"┣⊳ 🔗 𝑯𝒐𝒘 𝒕𝒐 𝑶𝒑𝒆𝒏\n"
        message += f"┃   {instructions_text_escaped}\n"
    
    message += "┃\n"
    message += "┗⊳ 𝑾𝑨𝑻𝑪𝑯 𝑵𝑶𝑾! 🎬\n\n"
    message += "𝑩𝒚 @NeonGhost_Network"
    
    return message

async def send_post_to_channel(context: ContextTypes.DEFAULT_TYPE, channel_id: str, user_data: dict, message: str):
    """Send post to channel"""
    keyboard = [[InlineKeyboardButton("🔗 𝑴𝒐𝒓𝒆 𝑪𝒉𝒂𝒏𝒏𝒆𝒍𝒔", url="https://linkzwallah.netlify.app/")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    thumbnail = user_data.get('thumbnail')
    thumbnail_type = user_data.get('thumbnail_type')
    
    if thumbnail:
        if thumbnail_type == 'photo':
            if isinstance(thumbnail, BytesIO):
                thumbnail.seek(0)
                await context.bot.send_photo(
                    chat_id=channel_id,
                    photo=thumbnail,
                    caption=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif isinstance(thumbnail, bytes):
                await context.bot.send_photo(
                    chat_id=channel_id,
                    photo=BytesIO(thumbnail),
                    caption=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_photo(
                    chat_id=channel_id,
                    photo=thumbnail,
                    caption=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                
        elif thumbnail_type == 'video':
            await context.bot.send_video(
                chat_id=channel_id,
                video=thumbnail,
                caption=message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        elif thumbnail_type == 'animation':
            await context.bot.send_animation(
                chat_id=channel_id,
                animation=thumbnail,
                caption=message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
    else:
        await context.bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

async def manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage channels interface"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    channels = list(channels_collection.find({"user_id": user_id}))
    
    keyboard = [[InlineKeyboardButton("📋 View All Channels", callback_data="view_channels")]] if channels else []
    keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if channels:
        message_text = f"📺 *Channel Management*\n\nYou have {len(channels)} channel(s) configured."
    else:
        message_text = "📺 *Channel Management*\n\nNo channels added yet. Add your first channel!"
    
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def view_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all channels"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    channels = list(channels_collection.find({"user_id": user_id}))
    
    if not channels:
        await query.edit_message_text(
            "📺 No channels found.\n\nUse the button below to add a channel.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")
            ], [
                InlineKeyboardButton("🔙 Back", callback_data="manage_channels")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyboard = []
    for channel in channels:
        channel_name = channel.get('channel_name', channel['channel_id'])
        keyboard.append([InlineKeyboardButton(
            f"🗑️ {channel_name}",
            callback_data=f"delete_channel_{str(channel['_id'])}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="manage_channels")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📺 *Your Channels ({len(channels)})*\n\n"
        f"Tap to delete a channel:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm channel deletion"""
    query = update.callback_query
    await query.answer()
    
    channel_id = query.data.split("_", 2)[2]
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_delete_{channel_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="view_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    channel = channels_collection.find_one({"_id": ObjectId(channel_id)})
    channel_name = channel.get('channel_name', channel['channel_id']) if channel else "Unknown"
    
    await query.edit_message_text(
        f"⚠️ *Delete Channel*\n\n"
        f"Are you sure you want to delete:\n*{channel_name}*?",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete channel from database"""
    query = update.callback_query
    await query.answer()
    
    channel_id = query.data.split("_", 2)[2]
    result = channels_collection.delete_one({"_id": ObjectId(channel_id)})
    
    if result.deleted_count > 0:
        await query.edit_message_text("✅ Channel deleted successfully!")
        await asyncio.sleep(1)
        await view_channels(update, context)
    else:
        await query.edit_message_text("❌ Error deleting channel.")

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add channel flow"""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("🆔 Channel ID", callback_data="add_by_id")],
        [InlineKeyboardButton("👤 Channel Username", callback_data="add_by_username")],
        [InlineKeyboardButton("🔗 Channel Link", callback_data="add_by_link")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="manage_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "➕ *Add New Channel*\n\n"
        "Choose how you want to add your channel:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_add_channel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add channel type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_by_id":
        context.user_data['add_channel_method'] = 'id'
        await query.edit_message_text(
            "🆔 *Add by Channel ID*\n\n"
            "Send me the channel ID (e.g., `-1001234567890`)\n\n"
            "To get channel ID:\n"
            "1. Forward any message from channel to @userinfobot\n"
            "2. Copy the 'Origin chat' ID\n\n"
            "Or send /cancel to go back",
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "add_by_username":
        context.user_data['add_channel_method'] = 'username'
        await query.edit_message_text(
            "👤 *Add by Username*\n\n"
            "Send me the channel username (e.g., `@mychannel`)\n\n"
            "Or send /cancel to go back",
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "add_by_link":
        context.user_data['add_channel_method'] = 'link'
        await query.edit_message_text(
            "🔗 *Add by Channel Link*\n\n"
            "Send me the channel link (e.g., `https://t.me/mychannel`)\n\n"
            "Or send /cancel to go back",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ADD_CHANNEL_DATA

async def handle_add_channel_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel data input"""
    user_input = update.message.text.strip()
    method = context.user_data.get('add_channel_method', 'id')
    
    channel_identifier = user_input
    
    if method == 'link':
        if 't.me/' in user_input:
            channel_identifier = '@' + user_input.split('t.me/')[-1].split('?')[0]
        else:
            await update.message.reply_text("❌ Invalid channel link format!")
            return ADD_CHANNEL_DATA
            
    elif method == 'username':
        if not user_input.startswith('@'):
            channel_identifier = '@' + user_input
    
    try:
        # Get chat info
        chat = await context.bot.get_chat(channel_identifier)
        channel_id = str(chat.id)
        channel_name = chat.title or chat.username or channel_id
        
        # Check if bot is admin
        is_admin = await is_bot_admin(context, channel_id)
        
        if not is_admin:
            await update.message.reply_text(
                f"❌ *Bot is not an admin in this channel!*\n\n"
                f"Channel: {channel_name}\n"
                f"ID: `{channel_id}`\n\n"
                f"Please add the bot as an admin with 'Post Messages' permission and try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADD_CHANNEL_DATA
        
        # Check if already exists
        existing = channels_collection.find_one({
            "user_id": update.effective_user.id,
            "channel_id": channel_id
        })
        
        if existing:
            await update.message.reply_text(
                f"⚠️ This channel is already added!\n\n{channel_name}",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADD_CHANNEL_DATA
        
        # Add channel
        channels_collection.insert_one({
            "user_id": update.effective_user.id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_username": chat.username,
            "added_at": datetime.now(IST)
        })
        
        await update.message.reply_text(
            f"✅ *Channel added successfully!*\n\n"
            f"📺 {channel_name}\n"
            f"🆔 `{channel_id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # If in post creation flow, show channel selection
        if 'video_link' in context.user_data:
            await show_channel_selection(update, context, new_message=True)
            return SELECT_CHANNELS
        else:
            await asyncio.sleep(1)
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
            await update.message.reply_text(
                "Use /start to continue",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ConversationHandler.END
            
    except TelegramError as e:
        await update.message.reply_text(
            f"❌ *Error adding channel:*\n{str(e)}\n\n"
            f"Please make sure:\n"
            f"• Channel ID/username is correct\n"
            f"• Bot is added to the channel\n"
            f"• Bot has admin rights",
            parse_mode=ParseMode.MARKDOWN
        )
        return ADD_CHANNEL_DATA
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")
        return ADD_CHANNEL_DATA

async def view_scheduled_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View scheduled posts"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    scheduled = list(posts_collection.find({
        "user_id": user_id,
        "status": "scheduled"
    }).sort("scheduled_time", 1).limit(10))
    
    if not scheduled:
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "📅 *No Scheduled Posts*\n\n"
            "You don't have any scheduled posts.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message_text = f"📅 *Upcoming Scheduled Posts ({len(scheduled)})*\n\n"
    keyboard = []
    
    for idx, post in enumerate(scheduled, 1):
        scheduled_time = post['scheduled_time']
        channel_name = post.get('channel_name', 'Unknown')
        time_str = scheduled_time.strftime("%d %b, %I:%M %p")
        
        message_text += f"{idx}. *{channel_name}*\n   ⏰ {time_str}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"🗑️ Delete Post {idx}",
            callback_data=f"delete_scheduled_{str(post['_id'])}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def view_posted_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View posted history"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    posted = list(posts_collection.find({
        "user_id": user_id,
        "status": "posted"
    }).sort("posted_time", -1).limit(15))
    
    if not posted:
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "📜 *No Posted History*\n\n"
            "You haven't posted anything yet.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message_text = f"📜 *Posted History (Last {len(posted)})*\n\n"
    
    for idx, post in enumerate(posted, 1):
        posted_time = post.get('posted_time')
        channel_name = post.get('channel_name', 'Unknown')
        
        if posted_time:
            time_str = posted_time.strftime("%d %b, %I:%M %p")
            message_text += f"{idx}. *{channel_name}*\n   ✅ {time_str}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def delete_scheduled_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a scheduled post"""
    query = update.callback_query
    await query.answer()
    
    post_id = query.data.split("_", 2)[2]
    result = posts_collection.delete_one({"_id": ObjectId(post_id)})
    
    if result.deleted_count > 0:
        await query.answer("✅ Scheduled post deleted!", show_alert=True)
        await view_scheduled_posts(update, context)
    else:
        await query.answer("❌ Error deleting post", show_alert=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    """Show main menu"""
    keyboard = [
        [InlineKeyboardButton("📝 Create New Post", callback_data="create_post")],
        [InlineKeyboardButton("📺 Manage Channels", callback_data="manage_channels")],
        [InlineKeyboardButton("📊 View Scheduled Posts", callback_data="view_scheduled")],
        [InlineKeyboardButton("📜 Posted History", callback_data="view_history")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = (
        "🏠 *Main Menu*\n\n"
        "Choose an option below:"
    )
    
    if from_callback or update.callback_query:
        # Always use callback query if available
        try:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # If edit fails, send new message
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        # Only use update.message if callback_query is not available
        if update.message:
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            logger.error("No message or callback_query available in update")

async def check_scheduled_posts(context: ContextTypes.DEFAULT_TYPE):
    """Check and post scheduled posts - FIXED VERSION"""
    try:
        now = datetime.now(IST)
        
        # Find all due posts
        due_posts = list(posts_collection.find({
            "status": "scheduled",
            "scheduled_time": {"$lte": now}
        }))
        
        logger.info(f"Checking scheduled posts... Found {len(due_posts)} due posts")
        
        for post in due_posts:
            try:
                post_data = post['post_data']
                
                # Reconstruct user_data format
                user_data_for_post = {
                    'video_link': post_data.get('video_link'),
                    'instructions_link': post_data.get('instructions_link'),
                    'instructions_text': post_data.get('instructions_text'),
                    'thumbnail_type': post_data.get('thumbnail_type')
                }
                
                # Handle thumbnail data
                if 'thumbnail' in post_data and post_data['thumbnail']:
                    thumbnail = post_data['thumbnail']
                    if isinstance(thumbnail, bytes):
                        user_data_for_post['thumbnail'] = BytesIO(thumbnail)
                    else:
                        user_data_for_post['thumbnail'] = thumbnail
                
                message = generate_post_message(user_data_for_post)
                
                # Send the post
                await send_post_to_channel(
                    context, 
                    post['channel_id'], 
                    user_data_for_post, 
                    message
                )
                
                # Update status to posted
                posts_collection.update_one(
                    {"_id": post['_id']},
                    {
                        "$set": {
                            "status": "posted",
                            "posted_time": now
                        }
                    }
                )
                
                logger.info(f"Successfully posted scheduled post {post['_id']} to {post['channel_id']}")
                
            except Exception as e:
                logger.error(f"Error posting scheduled post {post['_id']}: {e}")
                # Mark as failed
                posts_collection.update_one(
                    {"_id": post['_id']},
                    {
                        "$set": {
                            "status": "failed",
                            "error": str(e),
                            "failed_at": now
                        }
                    }
                )
                
    except Exception as e:
        logger.error(f"Error in check_scheduled_posts: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation"""
    await update.message.reply_text(
        "❌ Operation cancelled.\n\nUse /start to return to menu."
    )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    
    try:
        if isinstance(update, Update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again with /start"
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "❌ An error occurred. Please try again with /start", 
                    show_alert=True
                )
    except Exception as e:
        logger.error(f"Error sending error message: {e}")

def main():
    """Main function to run the bot"""
    # Initialize database
    init_db()
    
    # Create application with optimized settings
    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=20.0
    )
    
    application = Application.builder()\
        .token(BOT_TOKEN)\
        .request(request)\
        .concurrent_updates(True)\
        .build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(create_post, pattern="^create_post$")
        ],
        states={
            THUMBNAIL: [
                MessageHandler(
                    filters.PHOTO | filters.VIDEO | filters.Document.IMAGE | 
                    filters.Document.VIDEO | filters.ANIMATION, 
                    receive_thumbnail
                ),
                CallbackQueryHandler(skip_thumbnail, pattern="^skip_thumbnail$")
            ],
            VIDEO_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_video_link)
            ],
            HOW_TO_OPEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_instructions),
                CallbackQueryHandler(skip_instructions, pattern="^skip_instructions$")
            ],
            SELECT_POSTING_TYPE: [
                CallbackQueryHandler(
                    handle_posting_type, 
                    pattern="^(post_now|schedule_post|back_to_menu)$"
                )
            ],
            SCHEDULE_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_time),
                CallbackQueryHandler(
                    handle_schedule_time, 
                    pattern="^(quick_time_|custom_time|back_to_posting_type)"
                )
            ],
            SELECT_CHANNELS: [
                CallbackQueryHandler(
                    handle_channel_selection, 
                    pattern="^(toggle_channel_.*|select_all|deselect_all|add_channel|confirm_channels|back_to_menu)$"
                )
            ],
            ADD_CHANNEL_TYPE: [
                CallbackQueryHandler(
                    handle_add_channel_type, 
                    pattern="^(add_by_id|add_by_username|add_by_link|manage_channels)$"
                )
            ],
            ADD_CHANNEL_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_channel_data)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    
    # Additional handlers
    application.add_handler(CallbackQueryHandler(manage_channels, pattern="^manage_channels$"))
    application.add_handler(CallbackQueryHandler(view_channels, pattern="^view_channels$"))
    application.add_handler(CallbackQueryHandler(delete_channel, pattern="^delete_channel_"))
    application.add_handler(CallbackQueryHandler(confirm_delete_channel, pattern="^confirm_delete_"))
    application.add_handler(CallbackQueryHandler(view_scheduled_posts, pattern="^view_scheduled$"))
    application.add_handler(CallbackQueryHandler(view_posted_history, pattern="^view_history$"))
    application.add_handler(CallbackQueryHandler(delete_scheduled_post, pattern="^delete_scheduled_"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^back_to_menu$"))
    
    # Job queue for scheduled posts - RUNS EVERY 30 SECONDS
    job_queue = application.job_queue
    job_queue.run_repeating(
        check_scheduled_posts, 
        interval=30,  # Check every 30 seconds
        first=5  # Start after 5 seconds
    )
    
    logger.info("Bot started successfully!")
    print("🤖 Bot is running!")
    print("📱 Open Telegram and send /start to your bot")
    print("⚙️  Scheduled posts are checked every 30 seconds")
    print("⚠️  Press Ctrl+C to stop the bot\n")
    
    # Run the bot
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        pool_timeout=30
    )

if __name__ == '__main__':
    main()
