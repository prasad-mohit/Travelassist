import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import random
import re

# Initialize session state
def init_session_state():
    if 'conversation' not in st.session_state:
        st.session_state.conversation = []
    if 'trip_details' not in st.session_state:
        st.session_state.trip_details = {
            "origin": "",
            "destination": "",
            "departure_date": "",
            "return_date": "",
            "travelers": 1,
            "trip_type": "one-way",
            "hotel_check_in": "",
            "hotel_check_out": ""
        }
    if 'current_step' not in st.session_state:
        st.session_state.current_step = "welcome"
    if 'search_in_progress' not in st.session_state:
        st.session_state.search_in_progress = False
    if 'results' not in st.session_state:
        st.session_state.results = {
            "flights": None,
            "hotels": None,
            "recommendations": None
        }
    if 'awaiting_confirmation' not in st.session_state:
        st.session_state.awaiting_confirmation = False

init_session_state()

# Configure Gemini
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# --- Amadeus Credentials ---
AMADEUS_API_KEY = st.secrets.get("AMADEUS_API_KEY")
AMADEUS_API_SECRET = st.secrets.get("AMADEUS_API_SECRET")

# Common airport codes and city names for better display
AIRPORT_CODES = {
    "DEL": "Delhi",
    "BOM": "Mumbai",
    "GOI": "Goa",
    "BLR": "Bangalore",
    "HYD": "Hyderabad",
    "CCU": "Kolkata",
    "MAA": "Chennai",
    "JFK": "New York",
    "LHR": "London"
}

# --- Helper Functions ---
async def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'client_credentials',
        'client_id': AMADEUS_API_KEY,
        'client_secret': AMADEUS_API_SECRET
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception as e:
        return None

async def search_flights(payload, token):
    if not token:
        return None
        
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception as e:
        return None

async def search_hotels(city_code, check_in, check_out, travelers, token):
    if not token:
        return None
        
    # First get hotel IDs
    url = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city"
    params = {
        'cityCode': city_code,
        'radius': 5,
        'radiusUnit': 'KM',
        'includeClosed': False,
        'bestRateOnly': True,
        'ratings': '3,4,5'
    }
    
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return None
                
                hotels_data = await resp.json()
                if not hotels_data.get('data'):
                    return None
                
                # Get offers for each hotel
                offers_url = "https://test.api.amadeus.com/v3/shopping/hotel-offers"
                all_offers = []
                
                for hotel in hotels_data['data'][:3]:  # Limit to 3 hotels
                    params = {
                        'hotelId': hotel['hotelId'],
                        'adults': travelers,
                        'checkInDate': check_in,
                        'checkOutDate': check_out,
                        'roomQuantity': 1
                    }
                    
                    async with session.get(offers_url, headers=headers, params=params) as offers_resp:
                        if offers_resp.status == 200:
                            offer_data = await offers_resp.json()
                            if offer_data.get('data'):
                                all_offers.extend(offer_data['data'])
                
                return {"data": all_offers} if all_offers else None
    except Exception as e:
        return None

def get_travel_recommendations(destination, dates):
    city_name = AIRPORT_CODES.get(destination, destination)
    prompt = f"""
    Create engaging travel recommendations for {city_name} during {dates}. Include:
    1. Top 3 attractions with brief descriptions
    2. 2-3 local foods to try
    3. One cultural tip
    4. Packing suggestion
    
    Keep it conversational and under 200 words.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Here are some things to do in {city_name}:\n\n(Recommendations could not be loaded at this time)"

def extract_trip_details(user_input):
    prompt = f"""
    Extract travel details from this query:
    "{user_input}"
    
    Return JSON with:
    - origin (IATA code)
    - destination (IATA code)
    - departure_date (YYYY-MM-DD)
    - return_date (YYYY-MM-DD if round trip)
    - travelers (number)
    - trip_type ("one-way" or "round-trip")
    
    Example:
    {{
        "origin": "DEL",
        "destination": "GOI",
        "departure_date": "2025-05-01",
        "return_date": "2025-05-10",
        "travelers": 2,
        "trip_type": "round-trip"
    }}
    
    Return ONLY the JSON object.
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
        return json.loads(response_text)
    except Exception as e:
        return None

def check_missing_details(details):
    required_fields = ['origin', 'destination', 'departure_date']
    if details.get('trip_type', 'one-way') == 'round-trip':
        required_fields.append('return_date')
    return [field for field in required_fields if not details.get(field)]

def build_flight_payload(details):
    origin_destinations = [{
        "id": "1",
        "originLocationCode": details.get("origin"),
        "destinationLocationCode": details.get("destination"),
        "departureDateTimeRange": {
            "date": details.get("departure_date"),
            "time": "10:00:00"
        }
    }]
    
    if details.get("trip_type") == "round-trip" and details.get("return_date"):
        origin_destinations.append({
            "id": "2",
            "originLocationCode": details.get("destination"),
            "destinationLocationCode": details.get("origin"),
            "departureDateTimeRange": {
                "date": details.get("return_date"),
                "time": "10:00:00"
            }
        })
    
    return {
        "currencyCode": "INR",
        "originDestinations": origin_destinations,
        "travelers": [
            {
                "id": str(i+1),
                "travelerType": "ADULT"
            } for i in range(details.get("travelers", 1))
        ],
        "sources": ["GDS"],
        "searchCriteria": {
            "maxFlightOffers": 3,
            "flightFilters": {
                "cabinRestrictions": [
                    {
                        "cabin": "ECONOMY",
                        "coverage": "MOST_SEGMENTS",
                        "originDestinationIds": ["1", "2"] if details.get("trip_type") == "round-trip" else ["1"]
                    }
                ]
            }
        }
    }

def format_flight_results(data):
    if not data or "data" not in data or not data["data"]:
        return None

    result = "### Flight Options\n\n"
    for idx, offer in enumerate(data["data"], 1):
        price = offer.get("price", {}).get("grandTotal", "N/A")
        duration = offer.get("itineraries", [{}])[0].get("duration", "").replace("PT", "").replace("H", "h ").replace("M", "m")
        
        result += f"#### Option {idx}: ₹{price}\n"
        result += f"**Duration:** {duration}\n"
        
        for seg in offer.get("itineraries", [{}])[0].get("segments", []):
            dep = seg.get("departure", {})
            arr = seg.get("arrival", {})
            result += f"- {dep.get('iataCode', '')} → {arr.get('iataCode', '')} | {seg.get('carrierCode', '')} {seg.get('number', '')}\n"
            result += f"  Depart: {dep.get('at', '')[:16].replace('T', ' ')}\n"
            result += f"  Arrive: {arr.get('at', '')[:16].replace('T', ' ')}\n"
        
        result += "\n---\n"
    
    return result

def format_hotel_results(data):
    if not data or "data" not in data or not data["data"]:
        return None

    result = "### Hotel Options\n\n"
    for idx, hotel in enumerate(data["data"], 1):
        name = hotel.get("hotel", {}).get("name", "Unknown Hotel")
        price = hotel.get("offers", [{}])[0].get("price", {}).get("total", "N/A")
        rating = hotel.get("hotel", {}).get("rating", "N/A")
        
        result += f"#### {name} {'⭐' * int(rating) if rating.isdigit() else ''}\n"
        result += f"**Price:** ₹{price}\n"
        result += f"**Room Type:** {hotel.get('offers', [{}])[0].get('room', {}).get('typeEstimated', {}).get('category', 'Standard')}\n"
        result += "\n---\n"
    
    return result

async def process_trip_details():
    st.session_state.search_in_progress = True
    
    # Get flights
    token_data = await get_amadeus_token()
    if token_data:
        token = token_data.get("access_token")
        payload = build_flight_payload(st.session_state.trip_details)
        flight_data = await search_flights(payload, token)
        st.session_state.results["flights"] = format_flight_results(flight_data)
        
        # Get hotels
        check_in = st.session_state.trip_details['departure_date']
        check_out = st.session_state.trip_details.get('return_date', 
                    (datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
        
        hotel_data = await search_hotels(
            st.session_state.trip_details['destination'],
            check_in,
            check_out,
            st.session_state.trip_details['travelers'],
            token
        )
        st.session_state.results["hotels"] = format_hotel_results(hotel_data)
    
    # Get recommendations
    dates = st.session_state.trip_details['departure_date']
    if st.session_state.trip_details.get('return_date'):
        dates += f" to {st.session_state.trip_details['return_date']}"
    
    st.session_state.results["recommendations"] = get_travel_recommendations(
        st.session_state.trip_details['destination'],
        dates
    )
    
    st.session_state.search_in_progress = False
    st.session_state.current_step = "show_results"
    st.rerun()

# --- Streamlit UI ---
st.set_page_config(page_title="Travel Assistant", layout="centered")
st.title("✈️ Travel Planning Assistant")

# Display conversation history
for msg in st.session_state.conversation:
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    else:
        st.chat_message("assistant").write(msg["content"])

# Get user input
user_input = st.chat_input("How can I help with your travel plans?")

if user_input and not st.session_state.search_in_progress:
    st.session_state.conversation.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    
    try:
        if st.session_state.current_step == "welcome":
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Hi there! I can help you plan your trip. Tell me where you're going and when, like: 'I want to fly from Delhi to Goa on May 5th with 2 people'"
            })
            st.chat_message("assistant").write("Hi there! I can help you plan your trip. Tell me where you're going and when, like: 'I want to fly from Delhi to Goa on May 5th with 2 people'")
            st.session_state.current_step = "collect_details"
        
        elif st.session_state.current_step == "collect_details":
            details = extract_trip_details(user_input)
            if details:
                for key in details:
                    if key in st.session_state.trip_details and details[key]:
                        st.session_state.trip_details[key] = details[key]
                
                missing = check_missing_details(st.session_state.trip_details)
                if missing:
                    questions = {
                        "origin": "Which city are you flying from? (e.g., DEL for Delhi)",
                        "destination": "Which city are you traveling to? (e.g., GOI for Goa)",
                        "departure_date": "When are you departing? (e.g., 2025-05-05)",
                        "return_date": "When will you be returning? (e.g., 2025-05-12)",
                        "travelers": "How many people are traveling?"
                    }
                    question = questions.get(missing[0], "")
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": question
                    })
                    st.chat_message("assistant").write(question)
                else:
                    # All details collected
                    summary = f"""Got it! You're traveling:
- From: {AIRPORT_CODES.get(st.session_state.trip_details['origin'], st.session_state.trip_details['origin'])}
- To: {AIRPORT_CODES.get(st.session_state.trip_details['destination'], st.session_state.trip_details['destination'])}
- Departure: {st.session_state.trip_details['departure_date']}"""
                    
                    if st.session_state.trip_details.get('return_date'):
                        summary += f"\n- Return: {st.session_state.trip_details['return_date']}"
                    
                    summary += f"\n- Travelers: {st.session_state.trip_details['travelers']}"
                    
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": summary + "\n\nLet me find the best options for you..."
                    })
                    st.chat_message("assistant").markdown(summary + "\n\nLet me find the best options for you...")
                    
                    # Start searching
                    asyncio.run(process_trip_details())
            else:
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "I didn't quite catch that. Could you tell me again where and when you're traveling? For example: 'I want to go to Goa from Delhi on May 5th with 2 people'"
                })
                st.chat_message("assistant").write("I didn't quite catch that. Could you tell me again where and when you're traveling? For example: 'I want to go to Goa from Delhi on May 5th with 2 people'")
        
        elif st.session_state.current_step == "show_results":
            # Show results in tabs
            tab1, tab2, tab3 = st.tabs(["Flights", "Hotels", "Recommendations"])
            
            with tab1:
                if st.session_state.results.get("flights"):
                    st.markdown(st.session_state.results["flights"])
                else:
                    st.info("No flights found for your search criteria.")
            
            with tab2:
                if st.session_state.results.get("hotels"):
                    st.markdown(st.session_state.results["hotels"])
                else:
                    st.info("No hotels found for your search criteria.")
            
            with tab3:
                if st.session_state.results.get("recommendations"):
                    st.markdown(st.session_state.results["recommendations"])
                else:
                    st.info("No recommendations available.")
            
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Here are your travel options! Would you like to plan another trip?"
            })
            st.chat_message("assistant").write("Here are your travel options! Would you like to plan another trip?")
            st.session_state.current_step = "follow_up"
        
        elif st.session_state.current_step == "follow_up":
            if "yes" in user_input.lower() or "another" in user_input.lower():
                init_session_state()
                st.rerun()
            else:
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Great! Let me know if you need anything else."
                })
                st.chat_message("assistant").write("Great! Let me know if you need anything else.")
    
    except Exception as e:
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "Sorry, I encountered an error. Let's try again."
        })
        st.chat_message("assistant").write("Sorry, I encountered an error. Let's try again.")
        st.session_state.current_step = "collect_details"

# Show loading spinner if search is in progress
if st.session_state.search_in_progress:
    with st.spinner("Searching for the best travel options..."):
        time.sleep(1)
