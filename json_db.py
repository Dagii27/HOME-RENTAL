# json_db.py (Final Enhanced Version)
import json
import os
from datetime import datetime
import threading

DB_FILE = '/var/data/listings_db.json'
db_lock = threading.Lock()

def _load_db():
    if not os.path.exists(DB_FILE):
        return {'brokers': {}, 'listings': {}}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read()
            if not content:
                return {'brokers': {}, 'listings': {}}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        return {'brokers': {}, 'listings': {}}

def _save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def atomic_set_status(post_id: str, from_status: str, to_status: str) -> bool:
    with db_lock:
        db = _load_db()
        listing = db.get('listings', {}).get(post_id)
        if listing and listing.get('status') == from_status:
            listing['status'] = to_status
            _save_db(db)
            return True
        return False

def update_listing_status(post_id, status, message_id=None, channel_id=None, text=None):
    with db_lock:
        db = _load_db()
        if post_id in db.get('listings', {}):
            listing = db['listings'][post_id]
            listing['status'] = status
            if message_id is not None:
                listing['message_id'] = message_id
            if channel_id is not None:
                listing['channel_id'] = channel_id
            if text is not None:
                listing['text'] = text
            _save_db(db)
            return True
        return False

def update_listing_price(post_id, new_price, new_text):
    with db_lock:
        db = _load_db()
        if post_id in db.get('listings', {}):
            listing = db['listings'][post_id]
            listing['details']['price'] = new_price
            listing['text'] = new_text
            listing['edit_count'] = listing.get('edit_count', 0) + 1
            _save_db(db)
            return True
        return False

def add_listing(broker_id, details, photo_file_ids):
    with db_lock:
        db = _load_db()
        timestamp = datetime.utcnow().timestamp()
        post_id = f"{int(timestamp)}_{broker_id}"
        db.setdefault('listings', {})[post_id] = {
            'broker_id': str(broker_id),
            'details': details,
            'photo_file_ids': photo_file_ids,
            'status': 'pending',
            'timestamp': datetime.utcnow().isoformat(),
            'message_id': None,
            'channel_id': None,
            'text': None,
            'edit_count': 0,
        }
        _save_db(db)
        return post_id

# --- NEW: Function to update a listing for resubmission ---
def update_listing_for_resubmission(post_id, new_details, new_photos):
    with db_lock:
        db = _load_db()
        if post_id in db.get('listings', {}):
            listing = db['listings'][post_id]
            listing['details'] = new_details
            listing['photo_file_ids'] = new_photos
            listing['status'] = 'pending' # Reset status for re-approval
            listing['timestamp'] = datetime.utcnow().isoformat() # Update timestamp
            _save_db(db)
            return True
        return False

# --- NEW: Function to delete a listing ---
def delete_listing(post_id):
    with db_lock:
        db = _load_db()
        if post_id in db.get('listings', {}):
            del db['listings'][post_id]
            _save_db(db)
            return True
        return False

def get_user_listings(user_id): # Removed status_filter
    db = _load_db()
    user_listings = []
    user_id_str = str(user_id)
    # Get all listings for the user, regardless of status (except 'taken')
    for post_id, listing in db.get('listings', {}).items():
        if str(listing.get('broker_id')) == user_id_str and listing.get('status') != 'taken':
            user_listings.append((post_id, listing))
    user_listings.sort(key=lambda x: x[1]['timestamp'], reverse=True)
    return user_listings

def is_broker_registered(user_id):
    db = _load_db()
    return str(user_id) in db.get('brokers', {})

def register_broker(user_id, phone_number, first_name, username):
    with db_lock:
        db = _load_db()
        user_id_str = str(user_id)
        if user_id_str not in db.get('brokers', {}):
            db.setdefault('brokers', {})[user_id_str] = {
                'phone_number': phone_number, 'first_name': first_name, 'username': username,
                'company_name': first_name, 'registration_date': datetime.utcnow().isoformat()
            }
            _save_db(db)
            return True
        return False

def update_broker_company_name(user_id, company_name):
    with db_lock:
        db = _load_db()
        user_id_str = str(user_id)
        if user_id_str in db.get('brokers', {}):
            db['brokers'][user_id_str]['company_name'] = company_name
            _save_db(db)

def get_broker_details(user_id):
    db = _load_db()
    return db.get('brokers', {}).get(str(user_id))

def get_listing_details(post_id):
    db = _load_db()
    return db.get('listings', {}).get(post_id)

def count_broker_listings(broker_id):
    db = _load_db()
    count = 0
    broker_id_str = str(broker_id)
    for listing in db.get('listings', {}).values():
        if str(listing.get('broker_id')) == broker_id_str and listing.get('status') in ['approved', 'taken']:
            count += 1
    return count

def search_listings_by_type_and_location(listing_type, location_keyword):
    db = _load_db()
    results = []
    for post_id, listing in db.get('listings', {}).items():
        if listing.get('status') != 'approved':
            continue
        details = listing.get('details', {})
        if details.get('listing_type') == listing_type and location_keyword.lower() in details.get('location', '').lower():
            results.append((post_id, listing))
    results.sort(key=lambda x: x[1]['timestamp'], reverse=True)
    return results