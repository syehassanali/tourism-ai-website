import logging
from logging.config import dictConfig

# Configure logging FIRST - THIS IS CRUCIAL
dictConfig({
    'version': 1,
    'formatters': {
        'simple': {
            'format': '[%(levelname)s] %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': 'WARNING'  # Only show warnings and above
        }
    },
    'root': {
        'level': 'WARNING',
        'handlers': ['console']
    }
})

from flask import Flask, request, jsonify, render_template
from flask_pymongo import PyMongo
import pymongo
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS, cross_origin
import requests
import os
from datetime import datetime, timezone, timedelta
import openai
from bson.objectid import ObjectId
from dotenv import load_dotenv
import random
import logging
import traceback
from flask_wtf.csrf import CSRFProtect
from bson import Decimal128


# Silence specific noisy loggers
loggers = [
    'pymongo', 'urllib3', 'werkzeug', 
    'googleapiclient', 'flask_pymongo'
]
for logger_name in loggers:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False

load_dotenv()

app = Flask(__name__, template_folder='../templates', static_folder='static')

CORS(app, 
    resources={
        r"/generate": {
            "origins": ["http://127.0.0.1:5500", "http://localhost:5500"],
            "allow_headers": ["Content-Type", "X-CSRFToken"],
            "methods": ["POST", "OPTIONS"],
            "supports_credentials": True
        }
    }
)

app.config.update({
    'SECRET_KEY': os.getenv('FLASK_SECRET_KEY', 'default-secret-key'),
    'WTF_CSRF_TIME_LIMIT': 3600,
    'MONGO_URI': os.getenv("MONGO_URI"),
    'DEBUG': False  # Force-disable Flask debug mode
})

csrf = CSRFProtect(app)

# Configure PyMongo with production settings
mongo = PyMongo(app, 
    connectTimeoutMS=30000,
    socketTimeoutMS=30000,
    serverSelectionTimeoutMS=30000,
    tls=True,
    tlsAllowInvalidCertificates=True,
    connect=False  # Defer connection until first use
)
users_collection = mongo.db.users
itinerary_collection = mongo.db.itineraries

# API Keys Configuration
API_KEYS = {
    "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
    "OPENWEATHER_API_KEY": os.getenv("OPENWEATHER_API_KEY"),
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    "UNSPLASH_API_KEY": os.getenv("UNSPLASH_API_KEY")
}
openai.api_key = API_KEYS["OPENAI_API_KEY"]

def check_mongo_connection():
    try:
        # Force connection initialization
        mongo.cx.server_info()
        logging.getLogger(__name__).info("MongoDB connection established")
    except Exception as e:
        logging.getLogger(__name__).critical(f"MongoDB connection failed: {str(e)}")
        raise

def create_indexes():
    itinerary_collection.create_index([("destination", pymongo.TEXT)])
    users_collection.create_index([("email", pymongo.ASCENDING)], unique=True)

check_mongo_connection()
create_indexes()

def convert_bson_types(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, Decimal128):
        return float(obj.to_decimal())
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [convert_bson_types(v) for v in obj]
    if isinstance(obj, dict):
        return {k: convert_bson_types(v) for k, v in obj.items()}
    return obj

def get_city_info(destination):
    try:
        wiki_params = {
            'action': 'query', 
            'format': 'json', 
            'titles': destination,
            'prop': 'extracts', 
            'exintro': True, 
            'explaintext': True
        }
        wiki_response = requests.get(
            'https://en.wikipedia.org/w/api.php', 
            params=wiki_params,
            timeout=10
        )
        wiki_response.raise_for_status()
        
        page = next(iter(wiki_response.json().get('query', {}).get('pages', {}).values()))
        description = page.get('extract', 'No description available')

        headers = {"Authorization": f"Client-ID {API_KEYS['UNSPLASH_API_KEY']}"}
        unsplash_response = requests.get(
            f'https://api.unsplash.com/search/photos?query={destination}&per_page=3',
            headers=headers,
            timeout=10
        )
        unsplash_response.raise_for_status()
        
        images = [img['urls']['regular'] for img in unsplash_response.json().get('results', [])]

        return {'description': description, 'images': images}
    except Exception as e:
        logging.error(f"City info error: {str(e)}")
        return {'description': 'Information unavailable', 'images': []}

def optimize_routes(places, start_location):
    try:
        if not places or not start_location:
            return places

        geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={start_location}&key={API_KEYS['GOOGLE_API_KEY']}"
        geo_response = requests.get(geocode_url, timeout=10)
        geo_response.raise_for_status()
        geo_data = geo_response.json()
        
        if not geo_data.get('results'):
            return places
            
        start_lat_lng = geo_data['results'][0]['geometry']['location']

        places_with_coords = []
        for place in places:
            try:
                geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={place['address']}&key={API_KEYS['GOOGLE_API_KEY']}"
                geo_response = requests.get(geocode_url, timeout=10)
                geo_response.raise_for_status()
                geo_data = geo_response.json()
                
                if geo_data.get('results'):
                    location = geo_data['results'][0]['geometry']['location']
                    places_with_coords.append({
                        **place,
                        'lat': location['lat'],
                        'lng': location['lng']
                    })
            except Exception as e:
                logging.error(f"Geocoding error: {str(e)}")
                continue

        if not places_with_coords:
            return places

        directions_url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            'origin': f"{start_lat_lng['lat']},{start_lat_lng['lng']}",
            'destination': f"{start_lat_lng['lat']},{start_lat_lng['lng']}",
            'waypoints': 'optimize:true|' + '|'.join([f"{p['lat']},{p['lng']}" for p in places_with_coords]),
            'key': API_KEYS['GOOGLE_API_KEY'],
            'mode': 'driving'
        }
        
        response = requests.get(directions_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get('status') == 'OK' and data.get('routes'):
            optimized_order = data['routes'][0]['waypoint_order']
            optimized_places = [places_with_coords[i] for i in optimized_order]
            
            legs = data['routes'][0]['legs']
            for i in range(len(optimized_places)):
                if i < len(legs):
                    optimized_places[i]['travel_time'] = legs[i]['duration']['text']
                    optimized_places[i]['travel_distance'] = legs[i]['distance']['text']
            
            return optimized_places
        return places_with_coords
    except Exception as e:
        logging.error(f"Routing error: {str(e)}")
        return places

def create_time_based_itinerary(places, travel_days):
    try:
        itinerary = {}
        max_activities_per_day = 5
        
        for day in range(1, travel_days + 1):
            day_plan = {
                "Morning (9AM-12PM)": [],
                "Afternoon (12PM-5PM)": [],
                "Evening (5PM-9PM)": []
            }
            current_time = datetime.strptime("09:00", "%H:%M")
            activities_added = 0
            
            for place in places:
                if activities_added >= max_activities_per_day:
                    break
                
                if not all(key in place for key in ['name', 'address', 'lat', 'lng']):
                    continue
                
                try:
                    activity_duration = timedelta(hours=2)
                    end_time = current_time + activity_duration
                    
                    if current_time.hour < 12:
                        slot = "Morning (9AM-12PM)"
                    elif current_time.hour < 17:
                        slot = "Afternoon (12PM-5PM)"
                    else:
                        slot = "Evening (5PM-9PM)"
                    
                    day_plan[slot].append({
                        "name": place['name'],
                        "address": place.get('address', 'Address not available'),
                        "start_time": current_time.strftime("%H:%M"),
                        "end_time": end_time.strftime("%H:%M"),
                        "travel_time": place.get('travel_time', '15 mins'),
                        "coordinates": {
                            "lat": place.get('lat', 0),
                            "lng": place.get('lng', 0)
                        }
                    })
                    
                    travel_minutes = int(str(place.get('travel_time', '15 mins')).split()[0])
                    current_time = end_time + timedelta(minutes=travel_minutes)
                    activities_added += 1
                except Exception as e:
                    logging.error(f"Activity processing error: {str(e)}")
                    continue
            
            itinerary[f"Day {day}"] = day_plan
        
        return itinerary
    except Exception as e:
        logging.error(f"Itinerary creation failed: {str(e)}")
        return {f"Day {i+1}": {"Morning": [], "Afternoon": [], "Evening": []} for i in range(travel_days)}

def fetch_places(query, max_results=5):
    try:
        places_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            'query': f"{query}",
            'key': API_KEYS['GOOGLE_API_KEY'],
            'language': 'en',
            'region': 'PK'
        }
        response = requests.get(places_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') != 'OK':
            return []

        results = data.get('results', [])[:max_results]
        
        return [{
            'name': p['name'],
            'address': p.get('formatted_address', 'Address not available'),
            'rating': p.get('rating', 3.0),
            'price_level': p.get('price_level', random.randint(1, 4))
        } for p in results]
    except Exception as e:
        logging.error(f"Places API error: {str(e)}")
        return []

def fetch_weather(destination, days):
    try:
        weather_url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            'q': destination,
            'appid': API_KEYS['OPENWEATHER_API_KEY'],
            'units': 'metric'
        }
        response = requests.get(weather_url, params=params, timeout=10)
        response.raise_for_status()
        forecasts = response.json().get('list', [])
        
        weather_data = []
        for i in range(days):
            target_date = datetime.now(timezone.utc) + timedelta(days=i)
            day_forecast = [
                f for f in forecasts 
                if datetime.fromtimestamp(f['dt'], tz=timezone.utc).date() == target_date.date()
            ]
            
            if day_forecast:
                try:
                    avg_temp = sum(f['main']['temp'] for f in day_forecast) / len(day_forecast)
                except ZeroDivisionError:
                    avg_temp = 0
                
                weather_data.append({
                    'date': target_date.strftime('%Y-%m-%d'),
                    'temp': round(avg_temp, 1),
                    'description': day_forecast[0]['weather'][0]['description'],
                    'icon': day_forecast[0]['weather'][0].get('icon', '02d')
                })
        return weather_data
    except Exception as e:
        logging.error(f"Weather API error: {str(e)}")
        return []

@app.route('/')
def home():
    return render_template('forum.html', google_api_key=API_KEYS["GOOGLE_API_KEY"])

@app.route('/generate', methods=['POST', 'OPTIONS'])
@csrf.exempt
@cross_origin(origins=["http://127.0.0.1:5500", "http://localhost:5500"],
              allow_headers=["Content-Type", "X-CSRFToken"],
              methods=["POST", "OPTIONS"],
              supports_credentials=True)
def generate_itinerary():
    try:
        app.logger.info("Received request headers: %s", request.headers)
        app.logger.info("Received request data: %s", request.get_data())
        data = request.get_json()

        required_fields = {
            'destination': str,
            'travel_days': int,
            'start_location': str,
            'activities': list,
            'travel_date': str,
            'budget': str,
            'companions': str
        }

        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({
                "error": "Missing required fields",
                "missing": missing_fields
            }), 400

        type_errors = []
        for field, expected_type in required_fields.items():
            if not isinstance(data[field], expected_type):
                type_errors.append({
                    "field": field,
                    "expected": expected_type.__name__,
                    "actual": type(data[field]).__name__
                })
        
        if type_errors:
            return jsonify({
                "error": "Invalid data types",
                "details": type_errors
            }), 400

        try:
            travel_days = int(data['travel_days'])
            if travel_days < 1 or travel_days > 14:
                return jsonify({"error": "Travel days must be between 1-14"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid travel days format"}), 400

        valid_activities = {'city', 'beaches', 'hiking', 'food'}
        submitted_activities = [a for a in data['activities'] if a in valid_activities]
        if not submitted_activities:
            return jsonify({"error": "No valid activities selected"}), 400

        city_info = get_city_info(data['destination'])
        if not city_info:
            city_info = {'description': 'No description available', 'images': []}

        places = []
        for activity in submitted_activities:
            activity_places = fetch_places(f"{activity} in {data['destination']}")
            if activity_places:
                places.extend(activity_places)

        if not places:
            return jsonify({"error": "No places found for selected activities"}), 404

        optimized_places = optimize_routes(places, data['start_location']) or places
        itinerary = create_time_based_itinerary(optimized_places, travel_days)
        weather = fetch_weather(data['destination'], travel_days)

        itinerary_data = {
            'destination': data['destination'],
            'start_location': data['start_location'],
            'travel_days': travel_days,
            'travel_date': data['travel_date'],
            'budget': data['budget'],
            'companions': data['companions'],
            'activities': submitted_activities,
            'city_info': city_info,
            'itinerary': itinerary,
            'weather': weather,
            'optimized_places': optimized_places,
            'created_at': datetime.now(timezone.utc)
        }

        result = itinerary_collection.insert_one(itinerary_data)
        itinerary_id = str(result.inserted_id)

        return jsonify({
            'itinerary_id': itinerary_id,
            'city_info': city_info,
            'itinerary': itinerary,
            'weather': weather,
            'map_data': {
                'start_location': data['start_location'],
                'places': optimized_places
            }
        }), 200

    except Exception as e:
        app.logger.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500


@app.route('/itinerary/<itinerary_id>')
def view_itinerary(itinerary_id):
    try:
        if not ObjectId.is_valid(itinerary_id):
            return render_template('error.html', error="Invalid itinerary ID"), 400
            
        obj_id = ObjectId(itinerary_id)
        itinerary = itinerary_collection.find_one({"_id": obj_id})
        
        if not itinerary:
            return render_template('error.html', error="Itinerary not found"), 404
            
        itinerary = convert_bson_types(itinerary)
        
        required_fields = ['destination', 'start_location', 'itinerary']
        for field in required_fields:
            if field not in itinerary:
                return render_template('error.html', error=f"Missing {field} in itinerary"), 400

        return render_template('results.html', 
                            itinerary=itinerary,
                            google_api_key=API_KEYS['GOOGLE_API_KEY'],
                            now=datetime.now(timezone.utc))
                            
    except Exception as e:
        logging.error(f"Itinerary Error: {traceback.format_exc()}")
        return render_template('error.html', error="Server error"), 500

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        required_fields = ['name', 'email', 'password', 'confirm_password']
        
        if not all(field in data for field in required_fields):
            return jsonify({"error": "All fields required"}), 400

        if data['password'] != data['confirm_password']:
            return jsonify({"error": "Passwords mismatch"}), 400

        if users_collection.find_one({"email": data['email']}):
            return jsonify({"error": "Email exists"}), 409

        user_data = {
            "name": data['name'],
            "email": data['email'],
            "password": generate_password_hash(data['password']),
            "created_at": datetime.now(timezone.utc)
        }
        
        users_collection.insert_one(user_data)
        return jsonify({"message": "User created"}), 201

    except Exception as e:
        logging.error(f"Signup error: {str(e)}")
        return jsonify({"error": "Registration failed"}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        if not all(field in data for field in ['email', 'password']):
            return jsonify({"error": "Email and password required"}), 400

        user = users_collection.find_one({"email": data['email']})
        if not user or not check_password_hash(user['password'], data['password']):
            return jsonify({"error": "Invalid credentials"}), 401

        return jsonify({
            "message": "Login successful",
            "user": {
                "name": user['name'],
                "email": user['email']
            }
        }), 200

    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return jsonify({"error": "Authentication failed"}), 500

@app.route('/test_db')
def test_db():
    try:
        mongo.cx.admin.command('ping')
        count = itinerary_collection.count_documents({})
        return jsonify({
            "status": "connected",
            "itinerary_count": count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error="Server error"), 500




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)