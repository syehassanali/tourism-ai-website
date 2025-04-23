from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import requests
import os
import datetime
import openai
from flask import render_template
from bson.objectid import ObjectId
from dotenv import load_dotenv  # Add this import

# Load environment variables first
load_dotenv()

app = Flask(__name__, template_folder='../templates', static_folder='../static')
CORS(app)

# Updated MongoDB Configuration
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
mongo = PyMongo(app)
users_collection = mongo.db.users
itinerary_collection = mongo.db['itineraries']

# Get API keys from environment
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route('/')
def home():
    return "Welcome to the Tourism AI Website!"


def fetch_gpt_suggestions(destination, preferences):
    """
    Use OpenAI GPT to suggest activities based on user preferences.
    """
    try:
        prompt = (
            f"I am planning a trip to {destination}. "
            f"My preferences include: {', '.join(preferences)}. "
            "Suggest some unique and enjoyable activities for me."
        )
        response = openai.Completion.create(
            engine="gpt-4o-mini",
            prompt=prompt,
            max_tokens=100,
            temperature=0.7,
        )
        suggestions = response.choices[0].text.strip().split("\n")
        return [s.strip("- ") for s in suggestions if s]  # Clean and format output
    except Exception as e:
        print(f"Error fetching GPT suggestions: {str(e)}")
        return ["Visit local markets", "Explore historical landmarks"]  # Fallback suggestions


def optimize_routes(places):
    """
    Optimize routes between places using Google Directions API.
    """
    if len(places) < 2:
        return places  # No optimization needed if fewer than 2 places

    try:
        base_url = "https://maps.googleapis.com/maps/api/directions/json"
        waypoints = "|".join([place["address"] for place in places[1:-1]])  # All except start and end
        params = {
            "origin": places[0]["address"],
            "destination": places[-1]["address"],
            "waypoints": waypoints,
            "key": GOOGLE_API_KEY,
        }

        response = requests.get(base_url, params=params)
        print("Request URL for route optimization:", response.url)  # Debugging log
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "OK":
                optimized_order = data["routes"][0]["waypoint_order"]
                optimized_places = [places[0]] + [places[i + 1] for i in optimized_order] + [places[-1]]

                # Add travel info to each place
                for i, leg in enumerate(data["routes"][0]["legs"]):
                    places[i]["travel_time"] = leg["duration"]["text"]
                    places[i]["travel_distance"] = leg["distance"]["text"]

                return optimized_places
            else:
                print("Google Directions API Error:", data.get("status"))
        else:
            print("HTTP Error:", response.status_code, response.text)
    except Exception as e:
        print("Error optimizing routes:", str(e))
    return places  # Return unoptimized places if API fails


# Simulated pricing data for budget filtering
def simulate_price():
    """Simulate pricing data for places."""
    import random
    return random.randint(20, 250)  # Simulated price in USD

def create_limited_itinerary(places, travel_days, max_per_day=3):
    """Distribute places into daily itineraries, with a maximum limit per day."""
    itinerary = {f"Day {i+1}": [] for i in range(travel_days)}

    for i, place in enumerate(places):
        day_index = i % travel_days  # Distribute across days
        if len(itinerary[f"Day {day_index + 1}"]) < max_per_day:
            itinerary[f"Day {day_index + 1}"].append(place)
    
    return itinerary

@app.route('/generate-itinerary', methods=['POST'])
def generate_itinerary():
    data = request.json
    destination = data.get('destination')
    travel_days = int(data.get('travel_days', 0))  # Convert to integer
    activities = data.get('activities', [])
    preferences = data.get('preferences', [])
    budget = data.get('budget', 'medium')

    print("Received Data:", data)  # Debugging log

    if not destination or not travel_days:
        return jsonify({"error": "Destination and travel days are required"}), 400

    try:
        # Save form data to MongoDB
        itinerary_id = mongo.db.itineraries.insert_one(data).inserted_id

        all_places = []

        # Fetch GPT suggestions
        print("Fetching GPT activity suggestions...")
        gpt_suggestions = fetch_gpt_suggestions(destination, preferences)
        print("GPT Suggestions:", gpt_suggestions)

        # Combine user-provided activities with GPT suggestions
        combined_activities = list(set(activities + gpt_suggestions))  # Remove duplicates

        # Simulated pricing data for budget filtering
        budget_levels = {'low': 50, 'medium': 100, 'high': 200}

        # Fetch places for each activity
        for activity in combined_activities:
            print(f"Fetching places for activity: {activity}")
            places = fetch_places(f"{activity} in {destination}", max_results=10)

            # Simulate pricing and filter by budget
            for place in places:
                place['price'] = simulate_price()  # Add simulated price
                if place['price'] <= budget_levels[budget]:
                    all_places.append(place)

        # Distribute places into daily itinerary with a max of 3 per day
        itinerary = create_limited_itinerary(all_places, travel_days, max_per_day=3)

        # Optimize routes for each day's itinerary
        for day, places in itinerary.items():
            print(f"Optimizing routes for {day}...")
            itinerary[day] = optimize_routes(places)

        # Fetch weather data
        print("Fetching weather data...")
        weather = fetch_weather(destination, travel_days)

        print("Generated Itinerary:", itinerary)
        print("Weather Forecast:", weather)
        
        # Save the generated itinerary back to MongoDB
        mongo.db.itineraries.update_one(
            {'_id': itinerary_id}, {"$set": {"itinerary": itinerary, "weather": weather}}
        )
        return jsonify({
            "message": "Itinerary generated successfully",
            "itinerary_id": str(itinerary_id),
            "itinerary": itinerary,
            "weather": weather
        }), 200
    except Exception as e:
        print("Error in itinerary generation:", str(e))
        return jsonify({"error": str(e)}), 500



#For testing
@app.route('/test-gpt-suggestions', methods=['POST'])
def test_gpt_suggestions():
    data = request.json
    destination = data.get('destination')
    preferences = data.get('preferences', [])

    if not destination:
        return jsonify({"error": "Destination is required"}), 400

    try:
        suggestions = fetch_gpt_suggestions(destination, preferences)
        return jsonify({
            "message": "GPT suggestions fetched successfully",
            "suggestions": suggestions
        }), 200

        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def fetch_places(query, location=None, radius=1000, max_results=5):
    """
    Fetch places from the Google Places API and limit the number of results.
    """
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "key": GOOGLE_API_KEY,
    }
    if location:
        params["location"] = location
    if radius:
        params["radius"] = radius

    try:
        response = requests.get(base_url, params=params)
        print("Request URL:", response.url)  # Debugging log
        if response.status_code == 200:
            data = response.json()
            print("API Response:", data)  # Debugging log
            results = data.get("results", [])
            # Limit results to the maximum specified
            return [
                {
                    "name": place.get("name"),
                    "address": place.get("formatted_address"),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("user_ratings_total")
                }
                for place in results[:max_results]
            ]
        else:
            print("HTTP Error:", response.status_code, response.text)
            response.raise_for_status()
    except Exception as e:
        print(f"Error fetching places for query '{query}': {str(e)}")
        return []


def create_itinerary(places, travel_days):
    """Split places into daily itineraries."""
    itinerary = {}
    total_places = len(places)
    places_per_day = max(1, total_places // travel_days)  # Ensure at least 1 place per day

    for day in range(1, travel_days + 1):
        start_index = (day - 1) * places_per_day
        end_index = start_index + places_per_day
        itinerary[f"Day {day}"] = places[start_index:end_index]

    # Add remaining places to the last day, if any
    if total_places % travel_days != 0:
        itinerary[f"Day {travel_days}"].extend(places[end_index:])

    return itinerary


def fetch_weather(destination, travel_days):
    """Fetch weather forecast for the destination."""
    weather_url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": destination,  # Specify the city name
        "appid": OPENWEATHER_API_KEY,  # Your API key
        "units": "metric"  # Metric units for temperature
    }

    try:
        response = requests.get(weather_url, params=params)
        response_data = response.json()
        print("Weather API Response:", response_data)  # Debugging log

        # Check for API errors
        if response_data.get("cod") != "200":
            raise Exception(f"Error fetching weather: {response_data.get('message', 'Unknown error')}")

        # Extract relevant weather information
        forecasts = response_data.get("list", [])
        weather_forecasts = []
        start_date = datetime.datetime.now()

        for day in range(travel_days):
            target_date = (start_date + datetime.timedelta(days=day)).strftime("%Y-%m-%d")
            daily_forecast = [
                forecast for forecast in forecasts
                if forecast["dt_txt"].startswith(target_date)
            ]

            if daily_forecast:
                avg_temp = sum(item["main"]["temp"] for item in daily_forecast) / len(daily_forecast)
                weather_forecasts.append({
                    "date": target_date,
                    "avg_temp": round(avg_temp, 1),
                    "description": daily_forecast[0]["weather"][0]["description"]
                })

        return weather_forecasts

    except Exception as e:
        print("Error in fetch_weather:", str(e))
        raise Exception(f"Error fetching weather: {str(e)}")

@app.route('/result/<itinerary_id>', methods=['GET'])
def get_itinerary_result(itinerary_id):
    try:
        # Find the itinerary document in MongoDB
        itinerary = itinerary_collection.find_one({"_id": ObjectId(itinerary_id)})
        
        if not itinerary:
            return jsonify({"error": "Itinerary not found"}), 404
        
        # Transform itinerary data
        raw_itinerary = itinerary.get('itinerary', {})
        formatted_itinerary = [
            {"day": day, "activities": activities}
            for day, activities in raw_itinerary.items()
        ]
        
        # Prepare the response data
        response_data = {
            "destination": itinerary.get('destination'),
            "travel_date": itinerary.get('travel_date'),
            "travel_days": itinerary.get('travel_days'),
            "budget": itinerary.get('budget'),
            "companions": itinerary.get('companions'),
            "activities": itinerary.get('activities', []),
            "itinerary": formatted_itinerary,  # Send the transformed itinerary
            "weather": itinerary.get('weather', [])
        }
        
        print("Response Data:", response_data)  # Debugging log
        return jsonify(response_data), 200
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500



# Route: Sign Up
@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        print("Signup data received:", data)  # Debug log

        # Extract and validate input
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')

        # Ensure all fields are provided
        if not all([name, email, password, confirm_password]):
            return jsonify({"error": "All fields are required"}), 400

        # Check if passwords match
        if password != confirm_password:
            return jsonify({"error": "Passwords do not match"}), 400

        # Check if the email already exists
        if users_collection.find_one({"email": email}):
            return jsonify({"error": "Email already registered"}), 400

        # Hash the password and save the user
        hashed_password = generate_password_hash(password)
        users_collection.insert_one({
            "name": name,
            "email": email,
            "password": hashed_password
        })

        return jsonify({"message": "User registered successfully"}), 201

    except Exception as e:
        print("Error during signup:", str(e))
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500


# Route: Login
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        print("Login data received:", data)  # Debug log

        # Extract input
        email = data.get('email')
        password = data.get('password')

        # Fetch user by email
        user = users_collection.find_one({"email": email})
        if not user:
            return jsonify({"error": "Invalid email or password"}), 401

        # Verify the password
        if not check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid email or password"}), 401

        return jsonify({"message": "Login successful"}), 200

    except Exception as e:
        print("Error during login:", str(e))
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500


if __name__ == "__main__":
    app.run(debug=True)
