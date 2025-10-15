from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from io import BytesIO
from PIL import Image
import html
import logging

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation
THUMBNAIL, VIDEO_LINK, HOW_TO_OPEN = range(3)

# Permanent thumbnail size
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# Bot token
BOT_TOKEN = "7008031473:AAH-ZLZXr5vM2X_0rdMcdSRsfRwG6zzqvYE"

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_data.clear()
    
    keyboard = [[InlineKeyboardButton("⏭️ Skip Thumbnail", callback_data="skip_thumbnail")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎨 *Welcome to Channel Post Generator Bot!*\n\n"
        "Let's create a beautiful post for your channel.\n\n"
        "📸 *Step 1:* Send me the thumbnail (Photo/Video/GIF)\n"
        "or click Skip if you don't want to add one.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return THUMBNAIL

# Resize thumbnail to permanent size
async def resize_media(file_bytes, is_photo=True):
    try:
        image = Image.open(BytesIO(file_bytes))
        
        # Convert RGBA to RGB if needed
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize maintaining aspect ratio
        image.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)
        
        # Create new image with permanent size and paste resized image in center
        final_image = Image.new('RGB', (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (0, 0, 0))
        x = (THUMBNAIL_WIDTH - image.width) // 2
        y = (THUMBNAIL_HEIGHT - image.height) // 2
        final_image.paste(image, (x, y))
        
        # Save to bytes
        output = BytesIO()
        final_image.save(output, format='JPEG', quality=95)
        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error resizing media: {e}")
        return None

# Handle thumbnail (photo, video, gif)
async def receive_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.photo:
            # Handle photo
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
            # Handle video
            video = update.message.video
            context.user_data['thumbnail'] = video.file_id
            context.user_data['thumbnail_type'] = 'video'
            
        elif update.message.animation:
            # Handle GIF
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

# Skip thumbnail callback
async def skip_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⏭️ Thumbnail skipped!\n\n"
        "🔗 *Step 2:* Send me the video link (URL)",
        parse_mode=ParseMode.MARKDOWN
    )
    return VIDEO_LINK

# Handle video link
async def receive_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Handle how to open instructions
async def receive_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instructions_link = update.message.text.strip()
    
    # Check if it's a URL
    if instructions_link.startswith('http://') or instructions_link.startswith('https://'):
        context.user_data['instructions_link'] = instructions_link
    else:
        context.user_data['instructions_text'] = instructions_link
    
    await generate_post(update, context)
    return ConversationHandler.END

# Skip instructions callback
async def skip_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("⏭️ Instructions skipped!")
    await generate_post(update, context, from_callback=True)
    return ConversationHandler.END

# Generate and send the final post
async def generate_post(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    user_data = context.user_data
    
    # Get data
    video_link = user_data.get('video_link')
    instructions_link = user_data.get('instructions_link')
    instructions_text = user_data.get('instructions_text')
    thumbnail = user_data.get('thumbnail')
    thumbnail_type = user_data.get('thumbnail_type')
    
    # Escape HTML special characters in links
    video_link_escaped = html.escape(video_link)
    
    # Create beautiful post format with italic bold font using HTML
    message = "╔══════════════════╗\n"
    message += "║ 🎥 𝑵𝑬𝑾 𝑽𝑰𝑫𝑬𝑶 𝑨𝑳𝑬𝑹𝑻 ║\n"
    message += "╚══════════════════╝\n"
    message += "┃\n"
    
    # Add download link with permanent text "𝑫𝒐𝒘𝒏𝒍𝒐𝒂𝒅" using HTML
    message += f'┣⊳ 📥 <a href="{video_link_escaped}">𝑫𝒐𝒘𝒏𝒍𝒐𝒂𝒅</a>\n'
    
    # Add instructions if provided
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
    
    # Create inline button for "More Channels"
    keyboard = [[InlineKeyboardButton("🔗 𝑴𝒐𝒓𝒆 𝑪𝒉𝒂𝒏𝒏𝒆𝒍𝒔", url="https://linkzwallah.netlify.app/")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if thumbnail:
            if thumbnail_type == 'photo':
                # Check if thumbnail is BytesIO or file_id
                if isinstance(thumbnail, BytesIO):
                    if from_callback:
                        await update.callback_query.message.reply_photo(
                            photo=thumbnail,
                            caption=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    else:
                        await update.message.reply_photo(
                            photo=thumbnail,
                            caption=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                else:
                    if from_callback:
                        await update.callback_query.message.reply_photo(
                            photo=thumbnail,
                            caption=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    else:
                        await update.message.reply_photo(
                            photo=thumbnail,
                            caption=message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
            elif thumbnail_type == 'video':
                if from_callback:
                    await update.callback_query.message.reply_video(
                        video=thumbnail,
                        caption=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_video(
                        video=thumbnail,
                        caption=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            elif thumbnail_type == 'animation':
                if from_callback:
                    await update.callback_query.message.reply_animation(
                        animation=thumbnail,
                        caption=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_animation(
                        animation=thumbnail,
                        caption=message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
            
            success_msg = "🎉 *Post generated successfully!*\n\n" \
                         "✅ You can now forward this post to your channel.\n" \
                         "📝 Use /start to create another post."
            
            if from_callback:
                await update.callback_query.message.reply_text(success_msg, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(success_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            # No thumbnail - send as text message
            if from_callback:
                await update.callback_query.message.reply_text(
                    message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                await update.callback_query.message.reply_text(
                    "🎉 *Post generated successfully!*\n\n"
                    "✅ You can now forward this post to your channel.\n"
                    "📝 Use /start to create another post.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                await update.message.reply_text(
                    "🎉 *Post generated successfully!*\n\n"
                    "✅ You can now forward this post to your channel.\n"
                    "📝 Use /start to create another post.",
                    parse_mode=ParseMode.MARKDOWN
                )
    except Exception as e:
        logger.error(f"Error generating post: {e}")
        error_msg = f"❌ Error generating post: {str(e)}\n\nPlease try again with /start"
        if from_callback:
            await update.callback_query.message.reply_text(error_msg)
        else:
            await update.message.reply_text(error_msg)

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Post creation cancelled.\n\nUse /start to begin again."
    )
    return ConversationHandler.END

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again with /start"
            )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

# Main function
def main():
    # Create custom request with longer timeout
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    
    # Create application with custom request
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Setup conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            THUMBNAIL: [
                MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.IMAGE | filters.Document.VIDEO | filters.ANIMATION, receive_thumbnail),
                CallbackQueryHandler(skip_thumbnail, pattern="^skip_thumbnail$")
            ],
            VIDEO_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_video_link)
            ],
            HOW_TO_OPEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_instructions),
                CallbackQueryHandler(skip_instructions, pattern="^skip_instructions$")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    
    # Start the bot
    logger.info("Bot is running...")
    print("🤖 Bot is running successfully!")
    print("📱 Open Telegram and send /start to your bot")
    print("⚠️ Press Ctrl+C to stop the bot")
    
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
