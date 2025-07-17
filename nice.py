# final_bot.py (Enhanced Business Version)
import logging
import re
from html import escape
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

import json_db as db

# --- SETUP: HARD-CODE YOUR VALUES HERE ---
BOT_TOKEN = "7775904095:AAFeXhY5XDYXqF4C4Oe09GnFm-V9a1fOymw"
CHANNEL_ID = "-1002865544996"
ADMIN_CHAT_ID = "-1002786518715"
LOCATION_HASHTAG = "#AddisAbaba"
BOT_USERNAME = "homeposterbot"
CHANNEL_USERNAME = "AddisHomeET"
WEBSITE = "addishome.et"

# --- CONFIGURATION ---
MAX_EDITS = 3
MAX_PHOTOS = 10

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- States for ConversationHandlers (MODIFIED) ---
COMPANY_NAME = 0
(
    LISTING_TYPE, LOCATION_INPUT, BEDROOM_CHOICE, BATHROOM_CHOICE,
    HOME_TYPE_CHOICE, EXACT_PRICE_INPUT, DESCRIPTION, PHOTOS, CONFIRMATION
) = range(1, 10)
SEARCH_TYPE, SEARCH_LOCATION = range(10, 12)
EDIT_PRICE = 12


# --- Keyboards & UI Helpers ---
def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["✍️ Post Listing", "🔍 Search Listings"],
        ["📋 My Listings", "❓ Help"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- REMOVED: get_location_keyboard() is no longer needed ---

def get_room_count_keyboard(room_type: str) -> InlineKeyboardMarkup:
    """Generates a keyboard for selecting room counts (bed or bath)."""
    prefix = "bed_" if room_type == "bed" else "bath_"
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"{prefix}{i}") for i in range(1, 4)],
        [InlineKeyboardButton(str(i), callback_data=f"{prefix}{i}") for i in range(4, 7)],
        [InlineKeyboardButton("7+", callback_data=f"{prefix}7+"), InlineKeyboardButton("Studio (0)", callback_data=f"{prefix}0")],
        [InlineKeyboardButton("Skip", callback_data=f"{prefix}skip")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_home_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Apartment", callback_data="hometype_Apartment"), InlineKeyboardButton("Condominium", callback_data="hometype_Condominium")],
        [InlineKeyboardButton("House / Villa", callback_data="hometype_House"), InlineKeyboardButton("Guesthouse", callback_data="hometype_Guesthouse")],
        [InlineKeyboardButton("Other", callback_data="hometype_Other")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_photos_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("✅ Done & Continue to Preview", callback_data="done_uploading")]]
    return InlineKeyboardMarkup(keyboard)

def _get_post_id_from_callback(data: str, prefix: str) -> str:
    return data[len(prefix):]

def _is_valid_price(price_text: str) -> bool:
    numeric_match = re.search(r'-?[\d,.]+', price_text)
    if not numeric_match: return False
    try:
        price_value = float(numeric_match.group(0).replace(',', ''))
        return price_value > 0
    except (ValueError, IndexError, AttributeError):
        return False

# --- Text Formatting ---
def format_user_facing_id(post_id: str) -> str:
    post_id = str(post_id);
    if '_' in post_id: return f"AHE-{post_id.split('_')[-1][-6:]}"
    return f"AHE-{post_id[-6:]}" if len(post_id) > 6 else f"AHE-{post_id}"

def format_public_post_text(details: dict, broker_id: int) -> str:
    listing_type = details.get('listing_type', 'rent')
    title_type = "FOR RENT" if listing_type == 'rent' else "FOR SALE"
    broker_info = db.get_broker_details(broker_id)
    company_name = broker_info.get("company_name", "Verified Broker") if broker_info else "Verified Broker"
    listing_count = db.count_broker_listings(broker_id)
    listing_text = f"{listing_count} Listings Posted" if listing_count != 1 else "1 Listing Posted"
    footer = (f"<b>{escape(company_name)}</b>\n"
              f"Verified Broker ✅\n"
              f"{listing_text}\n————————————————————\n"
              f"From: {WEBSITE} | @{BOT_USERNAME} | @{CHANNEL_USERNAME}")
    hashtags = generate_hashtags(details)
    def e(text): return escape(str(text))

    # Price formatting
    price_str = details.get('price', 'Contact for price')
    try:
        price_num = int(re.sub(r'[^\d]', '', price_str))
        price_suffix = "/month" if listing_type == 'rent' else ""
        formatted_price = f"{price_num:,} ETB{price_suffix}"
    except (ValueError, TypeError):
        formatted_price = price_str

    # Description snippet
    description = details.get('description', '')
    desc_snippet = (description[:150] + '...') if len(description) > 150 else description

    # Building the core info block
    info_lines = [
        f"<b>📍 Location:</b> {e(details.get('location', 'N/A'))}",
        f"<b>💰 Price:</b> {e(formatted_price)}"
    ]
    if details.get('home_type') and details.get('home_type') not in ["Other", "N/A"]:
        info_lines.append(f"<b>🏠 Home Type:</b> {e(details.get('home_type'))}")
    if details.get('bedrooms') and details.get('bedrooms') != 'N/A':
        info_lines.append(f"<b>🛏️ Rooms:</b> {e(details.get('bedrooms'))} Bed, {e(details.get('bathrooms', 'N/A'))} Bath")
    if desc_snippet:
         info_lines.append(f"\n<b>📝 Description:</b> {e(desc_snippet)}")

    info_block = "\n".join(info_lines)

    return (f"<b>✨ NEW LISTING: {title_type} ✨</b>\n\n"
            f"{info_block}\n\n"
            f"<b>Click the button below to see all photos and get the broker's contact details instantly.</b> 👇\n\n"
            f"{footer}\n\n{hashtags}")

def format_admin_approval_caption(details: dict, broker_info: dict) -> str:
    title = "FOR RENT" if details.get('listing_type') == 'rent' else "FOR SALE"
    home_type_line = f"<b>Type:</b> {escape(details.get('home_type', 'N/A'))}\n"
    rooms_line = f"<b>Rooms:</b> {escape(details.get('bedrooms', 'N/A'))} Bed, {escape(details.get('bathrooms', 'N/A'))} Bath\n"
    return (f"<b>{title}</b>\n\n"
            f"<b>Location:</b> {escape(details.get('location', 'N/A'))}\n"
            f"{home_type_line}"
            f"{rooms_line}"
            f"<b>Exact Price:</b> {escape(details.get('price', 'N/A'))}\n\n"
            f"<b>Description:</b>\n{escape(details.get('description', 'N/A'))}\n\n"
            f"-----------------------------------------\n"
            f"<b>Broker Verification (Call to Confirm)</b>\n"
            f"<b>Name:</b> {escape(broker_info.get('first_name', 'N/A'))}\n"
            f"<b>Phone:</b> <code>{escape(broker_info.get('phone_number', 'N/A'))}</code>")

def generate_hashtags(details):
    type_tag = f"#{'ForRent' if details.get('listing_type') == 'rent' else 'ForSale'}"
    location_tag = f"#{re.sub(r'[^a-zA-Z0-9]', '', details.get('location', '').split(',')[0])}" if details.get('location') else ""
    home_type = details.get('home_type')
    home_type_tag = f"#{re.sub(r'[^a-zA-Z0-9]', '', home_type)}" if home_type and home_type != "Other" else ""
    tags = [type_tag, location_tag, home_type_tag, LOCATION_HASHTAG]
    return " ".join(tag for tag in tags if tag)

# --- CORE BOT LOGIC (START, REGISTRATION) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if context.args and context.args[0]:
        try:
            action, post_id = context.args[0].split('_', 1)
            listing = db.get_listing_details(post_id)
            if not listing: await update.message.reply_text("Sorry, this listing is no longer available."); return ConversationHandler.END
            if listing['status'] == 'taken': await update.message.reply_text("<b>This property is no longer available.</b>", parse_mode=ParseMode.HTML); return ConversationHandler.END
            if action == "view":
                await update.message.reply_text(f"Loading listing <code>{format_user_facing_id(post_id)}</code>...", parse_mode=ParseMode.HTML)
                photos = listing.get('photo_file_ids', [])
                if photos:
                    try: await context.bot.send_media_group(chat_id=user.id, media=[InputMediaPhoto(media=pid) for pid in photos])
                    except BadRequest as e: logger.error(f"Failed to send media group for post {post_id}: {e}"); await update.message.reply_text("An error occurred while loading the photos.")
                else: await update.message.reply_text("<i>(No photos were provided for this listing)</i>", parse_mode=ParseMode.HTML)
                broker_info = db.get_broker_details(listing['broker_id'])
                if not broker_info: await update.message.reply_text("Sorry, broker information could not be found."); return ConversationHandler.END
                contact_message = (f"<b>Contact details for listing {format_user_facing_id(post_id)}:</b>\n\n"
                                   f"<b>Broker:</b> {escape(broker_info.get('first_name', 'N/A'))}\n"
                                   f"<b>Phone:</b> <code>{escape(broker_info.get('phone_number', 'N/A'))}</code>\n\n"
                                   "Feel free to call them to arrange a viewing.")
                await update.message.reply_text(contact_message, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
                return ConversationHandler.END
            elif action == "contact":
                broker_info = db.get_broker_details(listing['broker_id'])
                if not broker_info: await update.message.reply_text("Sorry, broker information could not be found."); return ConversationHandler.END
                await update.message.reply_text(f"<b>Contact details for listing {format_user_facing_id(post_id)}:</b>\n\n<b>Broker:</b> {escape(broker_info.get('first_name', 'N/A'))}\n<b>Phone:</b> <code>{escape(broker_info.get('phone_number', 'N/A'))}</code>", parse_mode=ParseMode.HTML)
                return ConversationHandler.END
        except (IndexError, ValueError): pass
    if db.is_broker_registered(user.id):
        await update.message.reply_text(f"👋 Welcome back, {user.first_name}. How can I help you today?", reply_markup=get_main_keyboard())
    else: await update.message.reply_text("<b>Welcome to ADDIS HOME 🏡</b>\nPlease register by sharing your contact to begin.", parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Share Contact to Register", request_contact=True)]], one_time_keyboard=True, resize_keyboard=True))
    return ConversationHandler.END

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user, contact = update.effective_user, update.effective_message.contact
    db.register_broker(user.id, contact.phone_number, user.first_name, user.username)
    await update.message.reply_text("🤝 Thank you! To complete your profile, please enter your <b>Company Name</b> or press Skip.", parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardMarkup([["Skip"]], resize_keyboard=True, one_time_keyboard=True))
    return COMPANY_NAME

async def get_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    company_name = update.effective_user.first_name if update.message.text.strip() == "Skip" else update.message.text.strip()
    db.update_broker_company_name(update.effective_user.id, company_name)
    await update.message.reply_text(f"✅ Registration complete, <b>{escape(company_name)}</b>! You're all set.", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    return ConversationHandler.END

# --- NEW DIRECT POSTING CONVERSATION ---
async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🚀 <b>Creating a New Listing</b>", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    await context.bot.send_message(update.effective_chat.id, "Is the property for rent or for sale?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏡 For Rent", callback_data="type_rent")], [InlineKeyboardButton("🔑 For Sale", callback_data="type_sale")]]))
    return LISTING_TYPE

# --- MODIFIED FUNCTION ---
async def handle_listing_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    context.user_data['details'] = {'listing_type': query.data.split('_', 1)[1]}; context.user_data['photos'] = []
    await query.message.edit_text(
        "📍 <b>Step 1: Please enter the property's location.</b>\n\n"
        "<i>(e.g., 'Bole, near Edna Mall' or 'CMC, behind St. Michael church')</i>",
        parse_mode=ParseMode.HTML
    )
    return LOCATION_INPUT

# --- MODIFIED FUNCTION: Renamed and simplified ---
async def handle_location_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.message.text.strip()
    if not location or len(location) < 5:
        await update.message.reply_text("That location is too short. Please be more specific and try again.")
        return LOCATION_INPUT
    context.user_data['details']['location'] = location
    await update.message.reply_text("🛏️ <b>Step 2: How many bedrooms?</b>", reply_markup=get_room_count_keyboard('bed'), parse_mode=ParseMode.HTML)
    return BEDROOM_CHOICE

# --- NEW HANDLERS for Room and Home Type ---
async def handle_bedroom_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    selection = query.data.split('bed_', 1)[1]
    context.user_data['details']['bedrooms'] = "N/A" if selection == 'skip' else selection
    await query.message.edit_text("🛁 <b>Step 3: How many bathrooms?</b>", reply_markup=get_room_count_keyboard('bath'), parse_mode=ParseMode.HTML)
    return BATHROOM_CHOICE

async def handle_bathroom_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    selection = query.data.split('bath_', 1)[1]
    context.user_data['details']['bathrooms'] = "N/A" if selection == 'skip' else selection
    await query.message.edit_text("🏠 <b>Step 4: What type of home is it?</b>", reply_markup=get_home_type_keyboard(), parse_mode=ParseMode.HTML)
    return HOME_TYPE_CHOICE

async def handle_home_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    home_type = query.data.split('hometype_', 1)[1]
    context.user_data['details']['home_type'] = home_type
    await query.message.edit_text("💰 <b>Step 5: Please enter the exact price</b>\n\n<i>(e.g., 25000)</i>", parse_mode=ParseMode.HTML)
    return EXACT_PRICE_INPUT

async def handle_exact_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    if not _is_valid_price(price_text): await update.message.reply_text("❌ Invalid price. It must be a positive number (e.g., '25000'). Please try again."); return EXACT_PRICE_INPUT
    context.user_data['details']['price'] = price_text
    await update.message.reply_text("📝 <b>Step 6: Please enter the description</b>\n\nInclude details like floor, and other amenities.", parse_mode=ParseMode.HTML)
    return DESCRIPTION

async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description_text = update.message.text.strip()
    if not description_text or len(description_text) < 15: await update.message.reply_text("That description is too short. Please provide more details."); return DESCRIPTION
    context.user_data['details']['description'] = description_text
    await update.message.reply_text(f"📸 <b>Step 7: Please upload photos</b>\n\nSend up to <b>{MAX_PHOTOS} photos</b>. Press 'Done' when finished.", reply_markup=get_photos_keyboard(), parse_mode=ParseMode.HTML)
    return PHOTOS

# --- Other Handlers (My Listings, Search, Edit, Admin, etc.) ---
async def my_listings_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📋 Loading your listings dashboard...", reply_markup=ReplyKeyboardRemove())
    user_listings = db.get_user_listings(update.effective_user.id)
    if not user_listings:
        await update.message.reply_text("You don't have any listings yet.", reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("Here are your current listings:")
        for post_id, listing in user_listings:
            details = listing['details']; status = listing.get('status', 'unknown'); status_icon, keyboard = "", []
            if status == 'approved': status_icon = "🟢 Active"; keyboard = [[InlineKeyboardButton("✅ Mark as Taken", callback_data=f"mark_taken_{post_id}"), InlineKeyboardButton("✏️ Edit Price", callback_data=f"edit_start_{post_id}")]]
            elif status == 'rejected': status_icon = "🔴 Rejected"; keyboard = [[InlineKeyboardButton("✏️ Edit & Resubmit", callback_data=f"resubmit_start_{post_id}"), InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{post_id}")]]
            if keyboard: await context.bot.send_message(update.effective_chat.id, f"<b>{escape(details.get('location', 'N/A'))}</b>\nStatus: <i>{status_icon}</i> | Price: {escape(details.get('price', 'N/A'))}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        await update.message.reply_text("You can manage your listings above or choose an option from the menu.", reply_markup=get_main_keyboard())

# --- MODIFIED FUNCTION ---
async def resubmit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); post_id = _get_post_id_from_callback(query.data, "resubmit_start_")
    listing = db.get_listing_details(post_id)
    if not listing or str(listing.get('broker_id')) != str(query.from_user.id): await query.edit_message_text("❌ Error: Not your listing."); return ConversationHandler.END
    context.user_data.clear(); context.user_data['edit_post_id'] = post_id; context.user_data['details'] = {'listing_type': listing['details']['listing_type']}; context.user_data['photos'] = listing.get('photo_file_ids', [])
    await query.message.edit_text("✏️ <b>Editing Rejected Listing...</b>", parse_mode=ParseMode.HTML)
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="📍 <b>Step 1: Please enter the updated location for your listing.</b>",
        parse_mode=ParseMode.HTML
    )
    return LOCATION_INPUT

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('edit_post_id') and not context.user_data.get('cleared_old_photos'):
        context.user_data['photos'] = []; context.user_data['cleared_old_photos'] = True
    if not update.message.photo: await update.message.reply_text("Please send a photo file."); return PHOTOS
    photos = context.user_data.get('photos', []);
    if len(photos) >= MAX_PHOTOS: await update.message.reply_text(f"Maximum {MAX_PHOTOS} photos reached.", reply_markup=get_photos_keyboard()); return PHOTOS
    photos.append(update.message.photo[-1].file_id)
    await update.message.reply_text(f"✅ Photo {len(photos)}/{MAX_PHOTOS} received.", reply_markup=get_photos_keyboard())
    return PHOTOS

async def show_confirmation_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_reply_markup(reply_markup=None)
    details = context.user_data['details']; photos = context.user_data.get('photos', [])
    home_type_line = f"<b>🏠 Home Type:</b> {escape(details.get('home_type', 'N/A'))}\n"
    rooms_line = f"<b>🛏️ Rooms:</b> {escape(details.get('bedrooms', 'N/A'))} Bed, {escape(details.get('bathrooms', 'N/A'))} Bath\n"
    preview_caption = (f"<b>📍 Location:</b> {escape(details.get('location', 'N/A'))}\n"
                       f"{home_type_line}"
                       f"{rooms_line}"
                       f"<b>💰 Price:</b> {escape(details.get('price', 'N/A'))}\n\n"
                       f"<b>📝 Description:</b>\n{escape(details.get('description', 'N/A'))}")
    await query.message.reply_text("✨ <b>Final Preview</b>\nPlease review your listing one last time.", parse_mode=ParseMode.HTML)
    if photos: await query.message.reply_media_group(media=[InputMediaPhoto(media=pid) for pid in photos])
    else: await query.message.reply_text("<i>(No photos were provided for this listing)</i>", parse_mode=ParseMode.HTML)
    await query.message.reply_text(f"<b>--- PREVIEW ---</b>\n\n{preview_caption}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit for Approval", callback_data="submit_post")], [InlineKeyboardButton("❌ Discard", callback_data="cancel_post")]]))
    return CONFIRMATION
    
async def search_listings_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🔍 <b>Search Listings</b>", reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    await update.message.reply_text("What are you looking for?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏡 For Rent", callback_data="search_rent")], [InlineKeyboardButton("🔑 For Sale", callback_data="search_sale")]]))
    return SEARCH_TYPE
async def search_handle_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); context.user_data['search_type'] = query.data.split('_')[1]; await query.edit_message_text("Please enter a location to search (e.g., Bole).")
    return SEARCH_LOCATION
async def search_handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location_keyword = update.message.text.strip(); listing_type = context.user_data.get('search_type'); results = db.search_listings_by_type_and_location(listing_type, location_keyword)
    if not results: await update.message.reply_text(f"😕 Sorry, no listings found for '<b>{escape(location_keyword)}</b>'.", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    else:
        response_text = f"✅ Found <b>{len(results)}</b> matching listing{'s' if len(results) > 1 else ''}:\n"
        for i, (post_id, listing) in enumerate(results[:10]):
            response_text += f"\n<b>{i+1}. {escape(listing['details'].get('location'))}</b>\n   💰 Price: {escape(listing['details'].get('price'))}\n   <a href='https://t.me/{BOT_USERNAME}?start=view_{post_id}'>➡️ View Details & Photos</a>"
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=get_main_keyboard())
    context.user_data.clear(); return ConversationHandler.END
async def edit_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); post_id = _get_post_id_from_callback(query.data, "edit_start_"); listing = db.get_listing_details(post_id)
    if not listing or str(listing.get('broker_id')) != str(query.from_user.id): await query.edit_message_text("❌ Error: Not your listing."); return ConversationHandler.END
    edits_left = MAX_EDITS - listing.get('edit_count', 0)
    if edits_left <= 0: await query.edit_message_text(f"❌ Maximum edits reached."); return ConversationHandler.END
    context.user_data['edit_post_id'] = post_id
    await query.message.edit_text(f"Current Price: <b>{escape(listing['details'].get('price', 'N/A'))}</b>\nPlease send the new <b>exact price</b>.", parse_mode=ParseMode.HTML)
    return EDIT_PRICE
async def handle_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_price = update.message.text.strip()
    if not _is_valid_price(new_price): await update.message.reply_text("❌ Invalid price. Must be a positive number."); return EDIT_PRICE
    post_id = context.user_data.get('edit_post_id'); listing = db.get_listing_details(post_id); listing['details']['price'] = new_price
    new_public_text = format_public_post_text(listing['details'], listing['broker_id'])
    try:
        await context.bot.edit_message_text(text=new_public_text, chat_id=listing['channel_id'], message_id=listing['message_id'], parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View Details & Photos", url=f"https://t.me/{BOT_USERNAME}?start=view_{post_id}")]]))
        db.update_listing_price(post_id, new_price, new_public_text)
        await update.message.reply_text("✅ Price updated successfully.", reply_markup=get_main_keyboard())
    except BadRequest as e: await update.message.reply_text(f"❌ Failed to update: {e}", reply_markup=get_main_keyboard())
    context.user_data.clear(); return ConversationHandler.END
async def submit_for_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); user_id = query.from_user.id
    details = context.user_data['details']; photos = context.user_data.get('photos', [])
    edit_post_id = context.user_data.get('edit_post_id')
    if edit_post_id: db.update_listing_for_resubmission(edit_post_id, details, photos); post_id = edit_post_id; submitted_text = "✅ Your updated listing has been resubmitted for review."
    else: post_id = db.add_listing(user_id, details, photos); submitted_text = "✅ Your new listing has been sent for review."
    broker_info = db.get_broker_details(user_id); admin_caption = format_admin_approval_caption(details, broker_info)
    keyboard = [[InlineKeyboardButton("Approve", callback_data=f"admin_approve_{post_id}"), InlineKeyboardButton("Reject", callback_data=f"admin_reject_{post_id}")]]
    try:
        if photos:
            media_group = [InputMediaPhoto(media=pid, caption=admin_caption if i == 0 else None, parse_mode=ParseMode.HTML) for i, pid in enumerate(photos)]
            await context.bot.send_media_group(chat_id=ADMIN_CHAT_ID, media=media_group); await context.bot.send_message(ADMIN_CHAT_ID, f"Approve/reject <code>{post_id}</code>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        else: await context.bot.send_message(ADMIN_CHAT_ID, admin_caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except Exception as e: logger.error(f"Failed to send to admin group for post {post_id}: {e}")
    await query.message.edit_text(submitted_text, parse_mode=ParseMode.HTML)
    await context.bot.send_message(chat_id=user_id, text="We will notify you of the outcome. What's next?", reply_markup=get_main_keyboard())
    context.user_data.clear(); return ConversationHandler.END
async def approve_listing(context: ContextTypes.DEFAULT_TYPE, post_id: str, approved_by: str) -> (bool, str):
    listing = db.get_listing_details(post_id);
    if not listing: return False, f"Listing {post_id} not found."
    public_text = format_public_post_text(listing['details'], listing['broker_id'])
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("View Details & Photos", url=f"https://t.me/{BOT_USERNAME}?start=view_{post_id}")]])
    try:
        sent_message = await context.bot.send_message(chat_id=CHANNEL_ID, text=public_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        db.update_listing_status(post_id, 'approved', message_id=sent_message.message_id, channel_id=sent_message.chat.id, text=public_text)
        try: await context.bot.pin_chat_message(chat_id=sent_message.chat.id, message_id=sent_message.message_id, disable_notification=True)
        except Exception as e: logger.warning(f"Could not pin message for {post_id}: {e}")
        await context.bot.send_message(listing['broker_id'], "🎉 <b>Congratulations! Your Listing is Live.</b>", parse_mode=ParseMode.HTML)
        return True, "Success"
    except Exception as e: return False, f"<b>Telegram API Error!</b>\nCould not post listing <code>{post_id}</code>.\n<b>Details:</b> {escape(str(e))}"
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    message_text = "Action cancelled. What would you like to do next?"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Action cancelled.")
    await update.effective_message.reply_text(message_text, reply_markup=get_main_keyboard())
    return ConversationHandler.END
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "<b>❓ Welcome to the ADDIS HOME Help Center!</b>\n\n"
        "Here’s how to use the bot:\n\n"
        "✍️ <b>Post Listing</b>\n"
        "Follow the simple step-by-step guide to post a new property. You'll be asked for a location, price, description, and photos.\n\n"
        "🔍 <b>Search Listings</b>\n"
        "Look for available properties based on type (rent/sale) and location keywords.\n\n"
        "📋 <b>My Listings</b>\n"
        "View and manage all your posts. You can mark active ones as 'taken', edit prices, or edit and resubmit rejected listings.\n\n"
        "<b>/cancel</b> - Use this command at any time to stop the current process (like creating a new listing) and return to the main menu."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
async def delete_listing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); post_id = _get_post_id_from_callback(query.data, "delete_")
    if db.delete_listing(post_id): await query.edit_message_text("✅ Listing permanently deleted.")
    else: await query.edit_message_text("❌ Error deleting.")
    await context.bot.send_message(chat_id=query.from_user.id, text="Returning to the main menu.", reply_markup=get_main_keyboard())
async def mark_as_taken_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); post_id = _get_post_id_from_callback(query.data, "mark_taken_"); listing = db.get_listing_details(post_id)
    if not listing or listing['status'] != 'approved': await query.edit_message_text("Not an active listing."); return
    if listing.get('message_id'):
        try:
            status_text = "RENTED" if listing['details']['listing_type'] == 'rent' else "SOLD"; new_text = f"<b>--- 🤝 {status_text} 🤝 ---</b>\n\n" + listing['text']
            await context.bot.edit_message_text(text=new_text, chat_id=listing['channel_id'], message_id=listing['message_id'], parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View Details & Photos", url=f"https://t.me/{BOT_USERNAME}?start=view_{post_id}")]]))
            db.update_listing_status(post_id, 'taken', text=new_text); await query.edit_message_text("✅ Listing marked as taken.")
        except BadRequest as e:
            if "not modified" in str(e).lower(): await query.edit_message_text("Already marked.")
            else: db.update_listing_status(post_id, 'taken'); await query.edit_message_text("✅ Marked in records (channel update failed).")
    else: db.update_listing_status(post_id, 'taken'); await query.edit_message_text("✅ Marked as taken in records.")
    await context.bot.send_message(chat_id=query.from_user.id, text="Returning to the main menu.", reply_markup=get_main_keyboard())
async def admin_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; post_id = _get_post_id_from_callback(query.data, "admin_approve_"); admin_user = query.from_user
    if db.atomic_set_status(post_id, 'pending', 'approved'):
        await query.answer("Processing..."); approved, msg = await approve_listing(context, post_id, admin_user.mention_html())
        if approved: await query.edit_message_text(f"✅ Listing <code>{post_id}</code> APPROVED by {admin_user.mention_html()}.", parse_mode=ParseMode.HTML)
        else: db.update_listing_status(post_id, 'pending'); await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
    else: await query.answer(f"Action already taken.", show_alert=True); await query.edit_message_reply_markup(reply_markup=None)
async def admin_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; post_id = _get_post_id_from_callback(query.data, "admin_reject_"); admin_user = query.from_user
    if db.atomic_set_status(post_id, 'pending', 'rejected'):
        await query.answer("Processing..."); listing = db.get_listing_details(post_id)
        if listing: await context.bot.send_message(listing['broker_id'], f"🔴 Your listing for '<i>{escape(listing['details']['location'])}</i>' was rejected. Please edit and resubmit from 'My Listings'.", parse_mode=ParseMode.HTML)
        await query.edit_message_text(f"❌ Listing <code>{post_id}</code> REJECTED by {admin_user.mention_html()}.", parse_mode=ParseMode.HTML)
    else: await query.answer("Action already taken.", show_alert=True); await query.edit_message_reply_markup(reply_markup=None)


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    
    # --- UPDATED CONVERSATION HANDLER with new states ---
    post_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Post Listing$"), post_start), CallbackQueryHandler(resubmit_start, pattern="^resubmit_start_")],
        states={
            LISTING_TYPE: [CallbackQueryHandler(handle_listing_type, pattern="^type_")],
            LOCATION_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location_input)],
            BEDROOM_CHOICE: [CallbackQueryHandler(handle_bedroom_choice, pattern="^bed_")],
            BATHROOM_CHOICE: [CallbackQueryHandler(handle_bathroom_choice, pattern="^bath_")],
            HOME_TYPE_CHOICE: [CallbackQueryHandler(handle_home_type_choice, pattern="^hometype_")],
            EXACT_PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exact_price_input)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)],
            PHOTOS: [MessageHandler(filters.PHOTO, handle_photos), CallbackQueryHandler(show_confirmation_preview, pattern="^done_uploading$")],
            CONFIRMATION: [CallbackQueryHandler(submit_for_review, pattern="^submit_post$"), CallbackQueryHandler(cancel_conversation, pattern="^cancel_post$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)], per_message=False
    )
    registration_conv = ConversationHandler(entry_points=[MessageHandler(filters.CONTACT, handle_contact)], states={COMPANY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_company_name)]}, fallbacks=[CommandHandler("cancel", cancel_conversation)])
    search_conv = ConversationHandler(entry_points=[MessageHandler(filters.Regex("^🔍 Search Listings$"), search_listings_start)], states={SEARCH_TYPE: [CallbackQueryHandler(search_handle_type, pattern="^search_")], SEARCH_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_handle_location)]}, fallbacks=[CommandHandler("cancel", cancel_conversation)])
    edit_conv = ConversationHandler(entry_points=[CallbackQueryHandler(edit_price_start, pattern=r"^edit_start_")], states={EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_price)]}, fallbacks=[CommandHandler("cancel", cancel_conversation)])

    application.add_handler(CommandHandler("start", start)); application.add_handler(registration_conv); application.add_handler(post_conv); application.add_handler(search_conv); application.add_handler(edit_conv)
    application.add_handler(MessageHandler(filters.Regex("^📋 My Listings$"), my_listings_start)); application.add_handler(CallbackQueryHandler(mark_as_taken_callback, pattern=r"^mark_taken_")); application.add_handler(CallbackQueryHandler(delete_listing_callback, pattern=r"^delete_"))
    application.add_handler(CommandHandler("help", help_command)); application.add_handler(MessageHandler(filters.Regex("^❓ Help$"), help_command))
    application.add_handler(CallbackQueryHandler(admin_approve_callback, pattern="^admin_approve_")); application.add_handler(CallbackQueryHandler(admin_reject_callback, pattern="^admin_reject_"))
    logger.info("Bot is starting up..."); application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
