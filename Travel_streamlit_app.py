import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# Initialize session state
def init_session_state():
    session_defaults = {
        'conversation': [],
        'trip_details': {
            "origin": "",
            "destination": "",
            "departure_date": "",
            "return_date": "",
            "travelers": 1,
            "trip_type": "one-way"
        },
        'current_step': "welcome",
        'search_in_progress': False,
        'results': {
            "flights": None,
            "hotels": None,
            "recommendations": None
        }
    }
    
    for key, value in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Configure Gemini
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# API Credentials
AMADEUS_API_KEY = st.secrets.get("AMADEUS_API_KEY")
AMADEUS_API_SECRET = st.secrets.get("AMADEUS_API_SECRET")

# Airport codes mapping
AIRPORT_CODES = {
    "DEL": "Delhi", "BOM": "Mumbai", "GOI": "Goa",
    "BLR": "Bangalore", "HYD": "Hyderabad", "CCU": "Kolkata",
    "MAA": "Chennai", "JFK": "New York", "LHR": "London"
}

# Custom CSS
st.markdown("""
<style>
    /* Chat messages */
    .user-message {
        background-color: #e3f2fd;
        border-radius: 15px 15px 0 15px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
    }
    .assistant-message {
        background-color: #f1f1f1;
        border-radius: 15px 15px 15px 0;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
    }
    /* Input box */
    .stTextInput>div>div>input {
        color: #333 !important;
        background-color: white !important;
    }
    /* Flight/hotel cards */
    .travel-card {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        background-color: white;
    }
</style>
""", unsafe_allow_html=True)

# Helper Functions
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
                return await resp.json() if resp.status == 200 else None
    except Exception:
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
                return await resp.json() if resp.status == 200 else None
    except Exception:
        return None

async def get_hotels(destination, check_in, check_out, travelers):
    """Simulated hotel search"""
    city = AIRPORT_CODES.get(destination, destination)
    return [
        {
            "name": f"Grand {city} Hotel",
            "price": 7500,
            "rating": 4,
            "address": f"123 Beach Road, {city}",
            "photo": "https://source.unsplash.com/random/300x200/?hotel"
        },
        {
            "name": f"{city} Palace",
            "price": 12000,
            "rating": 5,
            "address": f"456 Main Street, {city}",
            "photo": "https://source.unsplash.com/random/300x200/?luxury+hotel"
        }
    ]

def get_travel_recommendations(destination, dates):
    city = AIRPORT_CODES.get(destination, destination)
    prompt = f"""Provide 3-5 travel recommendations for {city} during {dates} 
    including attractions, food, and cultural tips in a concise paragraph."""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        return f"Top things to do in {city}:\n\n(Recommendations unavailable)"

def extract_trip_details(user_input):
    prompt = f"""Extract travel details from: "{user_input}"
    Return JSON with: origin (IATA), destination (IATA), 
    departure_date (YYYY-MM-DD), return_date (if round trip), 
    travelers (number), trip_type ("one-way" or "round-trip")"""
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.strip().strip('```json').strip('```'))
    except Exception:
        return None

def build_flight_payload(details):
    payload = {
        "currencyCode": "INR",
        "originDestinations": [{
            "id": "1",
            "originLocationCode": details["origin"],
            "destinationLocationCode": details["destination"],
            "departureDateTimeRange": {
                "date": details["departure_date"],
                "time": "10:00:00"
            }
        }],
        "travelers": [{"id": str(i+1), "travelerType": "ADULT"} 
                     for i in range(details["travelers"])],
        "sources": ["GDS"],
        "searchCriteria": {"maxFlightOffers": 3}
    }
    
    if details["trip_type"] == "round-trip" and details.get("return_date"):
        payload["originDestinations"].append({
            "id": "2",
            "originLocationCode": details["destination"],
            "destinationLocationCode": details["origin"],
            "departureDateTimeRange": {
                "date": details["return_date"],
                "time": "10:00:00"
            }
        })
    return payload

async def process_trip():
    st.session_state.search_in_progress = True
    
    # Get flights
    token = await get_amadeus_token()
    if token:
        flights = await search_flights(
            build_flight_payload(st.session_state.trip_details),
            token["access_token"]
        )
        st.session_state.results["flights"] = flights
    
    # Get hotels
    check_in = st.session_state.trip_details["departure_date"]
    check_out = st.session_state.trip_details.get("return_date", 
                (datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d"))
    
    st.session_state.results["hotels"] = await get_hotels(
        st.session_state.trip_details["destination"],
        check_in,
        check_out,
        st.session_state.trip_details["travelers"]
    )
    
    # Get recommendations
    dates = st.session_state.trip_details["departure_date"]
    if st.session_state.trip_details.get("return_date"):
        dates += f" to {st.session_state.trip_details['return_date']}"
    
    st.session_state.results["recommendations"] = get_travel_recommendations(
        st.session_state.trip_details["destination"],
        dates
    )
    
    st.session_state.search_in_progress = False
    st.session_state.current_step = "show_results"
    st.rerun()

# Streamlit UI
st.set_page_config(
    page_title="TravelEase Assistant",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ TravelEase Assistant")
st.markdown("Your personal travel planning companion")

# Display conversation
for msg in st.session_state.conversation:
    st.markdown(f"""
    <div class="{'user' if msg['role']=='user' else 'assistant'}-message">
        {msg["content"]}
    </div>
    """, unsafe_allow_html=True)

# User input
if user_input := st.chat_input("Where would you like to travel?"):
    st.session_state.conversation.append({"role": "user", "content": user_input})
    
    try:
        if st.session_state.current_step == "welcome":
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Welcome! Tell me your travel plans like: 'I want to fly from Delhi to Goa on May 5th with 2 people'"
            })
            st.session_state.current_step = "collect_details"
        
        elif st.session_state.current_step == "collect_details":
            if details := extract_trip_details(user_input):
                st.session_state.trip_details.update(
                    {k: v for k, v in details.items() if v}
                )
                
                missing = [
                    f for f in ['origin', 'destination', 'departure_date'] 
                    if not st.session_state.trip_details.get(f)
                ]
                if st.session_state.trip_details.get("trip_type") == "round-trip":
                    missing.append("return_date") if not st.session_state.trip_details.get("return_date") else None
                
                if missing:
                    prompts = {
                        "origin": "Which city are you flying from? (e.g., DEL)",
                        "destination": "Where are you flying to? (e.g., GOI)",
                        "departure_date": "When are you departing? (YYYY-MM-DD)",
                        "return_date": "When will you return? (YYYY-MM-DD)",
                        "travelers": "How many people are traveling?"
                    }
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": prompts[missing[0]]
                    })
                else:
                    summary = f"""Got it! Traveling from {st.session_state.trip_details['origin']} to {
                        st.session_state.trip_details['destination']} on {
                        st.session_state.trip_details['departure_date']}"""
                    if st.session_state.trip_details.get("return_date"):
                        summary += f", returning {st.session_state.trip_details['return_date']}"
                    summary += f" with {st.session_state.trip_details['travelers']} traveler(s)."
                    
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": f"{summary}\n\nSearching for options..."
                    })
                    asyncio.run(process_trip())
            else:
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "I didn't understand. Try something like: 'Flight from Delhi to Mumbai on June 10th'"
                })
        
        elif st.session_state.current_step == "show_results":
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Here are your options! Need anything else?"
            })
            st.session_state.current_step = "follow_up"
        
        elif st.session_state.current_step == "follow_up":
            if "yes" in user_input.lower():
                init_session_state()
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Great! Where would you like to go?"
                })
            else:
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Happy travels! Come back anytime."
                })
        
        st.rerun()
    
    except Exception:
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "Something went wrong. Let's try again."
        })
        st.session_state.current_step = "collect_details"
        st.rerun()

# Display results
if st.session_state.current_step == "show_results":
    with st.expander("✈️ Flight Options", expanded=True):
        if st.session_state.results["flights"]:
            for offer in st.session_state.results["flights"].get("data", [])[:3]:
                price = offer["price"]["grandTotal"]
                st.markdown(f"**₹{price}**")
                for seg in offer["itineraries"][0]["segments"]:
                    st.write(f"{seg['departure']['iataCode']}→{seg['arrival']['iataCode']} "
                            f"{seg['carrierCode']}{seg['number']} "
                            f"{seg['departure']['at'][11:16]}-{seg['arrival']['at'][11:16]}")
        else:
            st.info("No flights found")
    
    with st.expander("🏨 Hotel Options"):
        if st.session_state.results["hotels"]:
            for hotel in st.session_state.results["hotels"][:3]:
                st.markdown(f"**{hotel['name']}** - ₹{hotel['price']} {'⭐' * hotel['rating']}")
                st.image(hotel["photo"], width=200)
        else:
            st.info("No hotels found")
    
    with st.expander("🌴 Recommendations"):
        if st.session_state.results["recommendations"]:
            st.write(st.session_state.results["recommendations"])
        else:
            st.info("No recommendations available")

# Loading indicator
if st.session_state.search_in_progress:
    st.spinner("Finding the best options...")
