import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import time

# Streamlit page configuration MUST BE FIRST
st.set_page_config(
    page_title="TravelEase Assistant",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
            "trip_type": "one-way",
            "budget": None,
            "class": "economy"
        },
        'current_step': "welcome",
        'search_in_progress': False,
        'results': {
            "flights": None,
            "hotels": None,
            "recommendations": None
        },
        'awaiting_input_for': None
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

# Verified image sources
AIRLINE_LOGOS = {
    "AI": "https://www.airindia.com/content/dam/air-india/airindia-revamp/logos/AI_Logo_Red_New.svg",
    "6E": "https://www.goindigo.in/content/dam/s6web/in/en/assets/logo/IndiGo_logo_2x.png",
    "SG": "https://www.spicejet.com/v1.svg",
    "default": "https://cdn-icons-png.flaticon.com/512/1169/1169168.png"
}

HOTEL_CHAINS = {
    "Marriott": "https://logos-world.net/wp-content/uploads/2021/08/Marriott-Logo.png",
    "Hilton": "https://logos-world.net/wp-content/uploads/2021/02/Hilton-Logo.png",
    "default": "https://cdn-icons-png.flaticon.com/512/2969/2969446.png"
}

PARTNER_LOGOS = [
    {"name": "Air India", "url": "https://www.airindia.com/content/dam/air-india/airindia-revamp/logos/AI_Logo_Red_New.svg"},
    {"name": "IndiGo", "url": "https://www.goindigo.in/content/dam/s6web/in/en/assets/logo/IndiGo_logo_2x.png"},
    {"name": "SpiceJet", "url": "https://www.spicejet.com/v1.svg"},
    {"name": "Marriott", "url": "https://logos-world.net/wp-content/uploads/2021/08/Marriott-Logo.png"}
]

AIRPORT_CODES = {
    "DEL": "Delhi", "BOM": "Mumbai", "GOI": "Goa",
    "BLR": "Bangalore", "HYD": "Hyderabad", "CCU": "Kolkata",
    "MAA": "Chennai", "JFK": "New York", "LHR": "London"
}

# Custom CSS
st.markdown("""
<style>
    .main {
        background-color: #f5f9ff;
    }
    .user-message {
        background-color: #4a8cff;
        color: white;
        border-radius: 15px 15px 0 15px;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        margin-left: auto;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .assistant-message {
        background-color: #ffffff;
        color: #333;
        border-radius: 15px 15px 15px 0;
        padding: 12px 16px;
        margin: 8px 0;
        max-width: 80%;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border: 1px solid #e1e1e1;
    }
    .stTextInput>div>div>input {
        color: #333 !important;
        background-color: white !important;
        border: 1px solid #ddd !important;
        border-radius: 20px !important;
        padding: 10px 15px !important;
    }
    .travel-card {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        background-color: white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    .travel-card:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .header {
        background: linear-gradient(135deg, #4a8cff 0%, #2a56d6 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .price-tag {
        background-color: #4a8cff;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        font-weight: bold;
        display: inline-block;
    }
    .rating {
        color: #FFD700;
        font-size: 18px;
    }
    .partner-logo {
        height: 60px;
        margin: 10px;
        filter: grayscale(30%);
        transition: all 0.3s ease;
    }
    .partner-logo:hover {
        filter: grayscale(0%);
        transform: scale(1.1);
    }
    .logo-container {
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100px;
    }
    .typing-indicator:after {
        content: '...';
        animation: typing 1s infinite;
    }
    @keyframes typing {
        0% { content: '.'; }
        33% { content: '..'; }
        66% { content: '...'; }
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
                if resp.status == 200:
                    return await resp.json()
                st.error("Failed to get Amadeus token")
                return None
    except Exception as e:
        st.error(f"Token error: {str(e)}")
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
                if resp.status == 200:
                    return await resp.json()
                st.error(f"Flight search failed: {resp.status}")
                return None
    except Exception as e:
        st.error(f"Search error: {str(e)}")
        return None

async def get_hotels(destination, check_in, check_out, travelers):
    """Simulated hotel search"""
    city = AIRPORT_CODES.get(destination, destination)
    return [
        {
            "name": f"Grand {city} Hotel",
            "price": 7500,
            "rating": 4.5,
            "address": f"123 Beach Road, {city}",
            "photo": "https://source.unsplash.com/random/300x200/?hotel",
            "chain": "Marriott"
        },
        {
            "name": f"{city} Palace",
            "price": 12000,
            "rating": 5,
            "address": f"456 Main Street, {city}",
            "photo": "https://source.unsplash.com/random/300x200/?luxury+hotel",
            "chain": "Hilton"
        }
    ]

def get_travel_recommendations(destination, dates):
    city = AIRPORT_CODES.get(destination, destination)
    prompt = f"""Provide 3-5 travel recommendations for {city} during {dates} 
    including attractions, food, and cultural tips in a concise paragraph."""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Recommendation error: {str(e)}")
        return f"Top things to do in {city}:\n\n(Recommendations unavailable)"

def extract_trip_details(user_input):
    prompt = f"""Analyze this travel request: "{user_input}"
    Extract and return ONLY valid JSON with these fields:
    - origin (IATA code like "DEL" or empty if not mentioned)
    - destination (IATA code like "GOI" or empty)
    - departure_date (YYYY-MM-DD or empty)
    - return_date (YYYY-MM-DD or empty if one-way)
    - travelers (number or default 1)
    - trip_type ("one-way" or "round-trip")
    - budget (number or null)
    - class ("economy", "business" or null)
    
    Example output for "I want to fly from Delhi to Goa on May 5th with 2 people":
    {{
        "origin": "DEL",
        "destination": "GOI",
        "departure_date": "2024-05-05",
        "return_date": "",
        "travelers": 2,
        "trip_type": "one-way",
        "budget": null,
        "class": "economy"
    }}"""
    
    try:
        response = model.generate_content(prompt)
        clean_json = response.text.strip().strip('```json').strip('```').strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"Extraction error: {str(e)}")
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
        "searchCriteria": {
            "maxFlightOffers": 3,
            "flightFilters": {
                "cabinRestrictions": [{
                    "cabin": details.get("class", "ECONOMY").upper(),
                    "coverage": "MOST_SEGMENTS",
                    "originDestinationIds": ["1"]
                }]
            }
        }
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
        payload["searchCriteria"]["flightFilters"]["cabinRestrictions"][0]["originDestinationIds"].append("2")
    
    if details.get("budget"):
        payload["searchCriteria"]["flightFilters"]["priceRange"] = {
            "maxPrice": details["budget"],
            "currency": "INR"
        }
    
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

def get_missing_fields(details):
    required = ['origin', 'destination', 'departure_date']
    if details.get('trip_type') == 'round-trip':
        required.append('return_date')
    return [field for field in required if not details.get(field)]

def get_prompt_for_field(field):
    prompts = {
        "origin": "Which city are you flying from? (e.g., DEL for Delhi)",
        "destination": "Where are you flying to? (e.g., GOI for Goa)",
        "departure_date": "When are you departing? (YYYY-MM-DD format)",
        "return_date": "When will you return? (YYYY-MM-DD format)",
        "travelers": "How many people are traveling?",
        "budget": "What's your budget (in INR)?",
        "class": "Preferred class? (economy/business)"
    }
    return prompts.get(field, f"Please provide {field.replace('_', ' ')}")

# UI Components
def show_partners():
    st.markdown("### Our Travel Partners")
    cols = st.columns(len(PARTNER_LOGOS))
    for i, partner in enumerate(PARTNER_LOGOS):
        with cols[i]:
            st.markdown(f'<div class="logo-container">', unsafe_allow_html=True)
            try:
                st.image(partner["url"], width=100, caption=partner["name"])
            except:
                st.markdown(f"**{partner['name']}**")
                st.image(AIRLINE_LOGOS["default"], width=60)
            st.markdown('</div>', unsafe_allow_html=True)

def show_conversation():
    for msg in st.session_state.conversation:
        role = "user" if msg['role'] == 'user' else 'assistant'
        st.markdown(f"""
        <div class="{role}-message">
            {msg["content"]}
        </div>
        """, unsafe_allow_html=True)
    
    if st.session_state.search_in_progress:
        st.markdown("""
        <div class="assistant-message">
            Searching for options<span class="typing-indicator"></span>
        </div>
        """, unsafe_allow_html=True)

def show_results():
    with st.expander("✈️ Flight Options", expanded=True):
        if st.session_state.results["flights"] and st.session_state.results["flights"].get("data"):
            for offer in st.session_state.results["flights"]["data"][:3]:
                airline_code = offer['itineraries'][0]['segments'][0]['carrierCode']
                airline_logo = AIRLINE_LOGOS.get(airline_code, AIRLINE_LOGOS['default'])
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.image(airline_logo, width=80)
                with col2:
                    price = offer["price"]["grandTotal"]
                    st.markdown(f"**<span class='price-tag'>₹{price}</span>**", unsafe_allow_html=True)
                    
                    for seg in offer["itineraries"][0]["segments"]:
                        st.write(f"**{seg['departure']['iataCode']} → {seg['arrival']['iataCode']}** "
                                f"{seg['carrierCode']}{seg['number']} "
                                f"{seg['departure']['at'][11:16]}-{seg['arrival']['at'][11:16]}")
                st.markdown("---")
        else:
            st.info("No flights found. Try adjusting your search criteria.")
    
    with st.expander("🏨 Hotel Options"):
        if st.session_state.results["hotels"]:
            for hotel in st.session_state.results["hotels"][:3]:
                chain_logo = HOTEL_CHAINS.get(hotel.get("chain", ""), HOTEL_CHAINS['default'])
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.image(hotel["photo"], width=150)
                with col2:
                    st.markdown(f"**{hotel['name']}**")
                    st.markdown(f"<div class='rating'>{'⭐' * int(hotel['rating'])}{'☆' * (5 - int(hotel['rating']))}</div>", unsafe_allow_html=True)
                    st.markdown(f"**<span class='price-tag'>₹{hotel['price']}</span>** per night", unsafe_allow_html=True)
                    st.markdown(f"📍 {hotel['address']}")
                    if hotel.get("chain"):
                        st.image(chain_logo, width=100)
                st.markdown("---")
        else:
            st.info("No hotels found")
    
    with st.expander("🌴 Travel Recommendations"):
        if st.session_state.results["recommendations"]:
            st.write(st.session_state.results["recommendations"])
        else:
            st.info("No recommendations available")

# Main App Flow
def handle_user_input(user_input):
    st.session_state.conversation.append({"role": "user", "content": user_input})
    
    try:
        if st.session_state.current_step == "welcome":
            system_msg = """
            You are a friendly travel assistant named TravelEase. Greet the user warmly,
            briefly explain your capabilities (e.g., book flights, hotels, offer travel tips),
            and encourage them to describe their trip naturally. Be human and conversational.
            """
            gemini_input = f"{system_msg}\\n\\nUser: {user_input}"

User: {user_input}"
            reply = model.generate_content(gemini_input).text.strip()
            st.session_state.conversation.append({"role": "assistant", "content": reply})
            st.session_state.current_step = "collect_details"

        elif st.session_state.current_step == "collect_details":
            if st.session_state.awaiting_input_for:
                # Store the user's response for the specific field we asked for
                st.session_state.trip_details[st.session_state.awaiting_input_for] = user_input
                st.session_state.awaiting_input_for = None

                missing = get_missing_fields(st.session_state.trip_details)
                if not missing:
                    origin_name = AIRPORT_CODES.get(st.session_state.trip_details['origin'], st.session_state.trip_details['origin'])
                    dest_name = AIRPORT_CODES.get(st.session_state.trip_details['destination'], st.session_state.trip_details['destination'])

                    summary = f"Great! ✈️ I'm searching for flights from {origin_name} to {dest_name} on {st.session_state.trip_details['departure_date']}"
                    if st.session_state.trip_details.get("return_date"):
                        summary += f", returning {st.session_state.trip_details['return_date']}"

                    summary += f" for {st.session_state.trip_details['travelers']} traveler(s)."

                    if st.session_state.trip_details.get("class") and st.session_state.trip_details["class"] != "economy":
                        summary += f"

Class: {st.session_state.trip_details['class'].title()}"
                    if st.session_state.trip_details.get("budget"):
                        summary += f"
Budget: ₹{st.session_state.trip_details['budget']}"

                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": f"{summary}

Hang tight while I look that up! 🔍"
                    })
                    asyncio.run(process_trip())
                else:
                    next_field = missing[0]
                    st.session_state.awaiting_input_for = next_field
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": get_prompt_for_field(next_field)
                    })
            else:
                if details := extract_trip_details(user_input):
                    st.session_state.trip_details.update(
                        {k: v for k, v in details.items() if v}
                    )
                    missing = get_missing_fields(st.session_state.trip_details)
                    if missing:
                        next_field = missing[0]
                        st.session_state.awaiting_input_for = next_field
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": get_prompt_for_field(next_field)
                        })
                    else:
                        origin_name = AIRPORT_CODES.get(st.session_state.trip_details['origin'], st.session_state.trip_details['origin'])
                        dest_name = AIRPORT_CODES.get(st.session_state.trip_details['destination'], st.session_state.trip_details['destination'])

                        summary = f"Awesome! I'm finding flights from {origin_name} to {dest_name} on {st.session_state.trip_details['departure_date']}"
                        if st.session_state.trip_details.get("return_date"):
                            summary += f", returning {st.session_state.trip_details['return_date']}"

                        summary += f" for {st.session_state.trip_details['travelers']} traveler(s)."

                        if st.session_state.trip_details.get("class") and st.session_state.trip_details["class"] != "economy":
                            summary += f"

Class: {st.session_state.trip_details['class'].title()}"
                        if st.session_state.trip_details.get("budget"):
                            summary += f"
Budget: ₹{st.session_state.trip_details['budget']}"

                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": f"{summary}

Let me pull that up real quick! 🛫"
                        })
                        asyncio.run(process_trip())
                else:
                    gemini_input = f"""
                    The user said: "{user_input}"
                    You are a friendly travel assistant. If their request is unclear, gently ask for more info.
                    Suggest how to describe their trip (like cities, dates, travelers). Give examples. Be warm and casual.
                    """
                    reply = model.generate_content(gemini_input).text.strip()
                    st.session_state.conversation.append({"role": "assistant", "content": reply})

        elif st.session_state.current_step == "show_results":
            if "yes" in user_input.lower() or "search" in user_input.lower():
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "What would you like to search for next? 😊"
                })
                init_session_state()
                st.session_state.current_step = "collect_details"
            else:
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Thank you for using TravelEase! Feel free to ask about your next adventure! 🌏"
                })

        st.rerun()

    except Exception as e:
        st.error(f"Error: {str(e)}")
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "Oops! Something went wrong. Let’s try that again! 🔁"
        })
        st.session_state.current_step = "collect_details"
        st.rerun()
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "Sorry, I encountered an error. Let's try again. What were you looking for?"
        })
        st.session_state.current_step = "collect_details"
        st.rerun()

# App Layout
st.markdown("""
<div class="header">
    <h1 style="color:white; margin:0;">✈️ TravelEase Assistant</h1>
    <p style="color:white; margin:0;">Your personal travel planning companion</p>
</div>
""", unsafe_allow_html=True)

show_partners()
show_conversation()

if st.session_state.current_step == "show_results":
    show_results()

# User input at bottom
if user_input := st.chat_input("Where would you like to travel?", key="chat_input"):
    handle_user_input(user_input)
