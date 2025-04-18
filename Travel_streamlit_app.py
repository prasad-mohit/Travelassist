import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import random

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
    if 'search_completed' not in st.session_state:
        st.session_state.search_completed = False
    if 'results' not in st.session_state:
        st.session_state.results = {
            "flights": None,
            "hotels": None,
            "recommendations": None
        }

init_session_state()

# Configure Gemini
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# --- Amadeus Credentials ---
AMADEUS_API_KEY = st.secrets.get("AMADEUS_API_KEY")
AMADEUS_API_SECRET = st.secrets.get("AMADEUS_API_SECRET")

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
                    error = await resp.text()
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
                
                for hotel in hotels_data['data'][:5]:  # Limit to 5 hotels
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
    # Enhanced prompt for more engaging responses
    prompt = f"""
    Create engaging travel recommendations for {destination} during {dates}. Include:
    
    1. A brief, enthusiastic intro about why {destination} is special during this time
    2. Top 3-4 attractions with a sentence about each (no long descriptions)
    3. 2-3 local food/drinks that visitors must try 
    4. One cultural tip or local custom travelers should know
    5. Quick seasonal advice (weather, events, crowds)
    
    Use a warm, conversational tone as if chatting with a friend. Include occasional emojis.
    Limit to 250-300 words total.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"I'd love to tell you more about {destination}, but I'm having trouble accessing that information right now."

def extract_trip_details(user_input, current_details):
    # Enhanced context-aware prompt
    prompt = f"""
    Analyze this travel request and extract details:
    "{user_input}"
    
    Current known details (leave as is if not mentioned in new request):
    {json.dumps(current_details, indent=2)}
    
    Return a JSON with any details you can find or that should be updated:
    - origin (IATA code)
    - destination (IATA code)
    - departure_date (YYYY-MM-DD)
    - return_date (YYYY-MM-DD if round trip)
    - travelers (number)
    - trip_type ("one-way" or "round-trip")
    
    Example output:
    {{
        "origin": "DEL",
        "destination": "GOI",
        "departure_date": "2025-05-01",
        "return_date": "2025-05-10",
        "travelers": 2,
        "trip_type": "round-trip"
    }}
    
    Return ONLY the JSON object, nothing else. Preserve existing values if not mentioned.
    """
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
        
        extracted_details = json.loads(response_text)
        
        # Merge with existing details (keep old values if not updated)
        merged_details = current_details.copy()
        for key, value in extracted_details.items():
            if value:  # Only update if there's actually a value
                merged_details[key] = value
                
        return merged_details
    except Exception as e:
        return current_details

def generate_conversational_response(context, user_input):
    prompt = f"""
    You are a friendly travel assistant helping a customer plan a trip.
    
    Current conversation context:
    {context}
    
    Latest user message:
    "{user_input}"
    
    Generate a warm, conversational response that addresses their message. 
    Keep it concise (2-3 sentences) but friendly.
    
    If they're asking about trip details, acknowledge what you understand so far.
    If they need to provide more information, ask in a natural way.
    Use light conversational elements like "Sounds exciting!" or "Great choice!"
    
    DON'T provide any specific flight or hotel data in your response.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "I understand! Let me help you with your travel plans."

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
            "maxFlightOffers": 5,
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

    markdown_result = "### ✈️ Flight Options\n\n"
    
    for idx, offer in enumerate(data["data"][:3], 1):  # Limit to top 3 flights
        price = offer.get("price", {}).get("grandTotal", "N/A")
        duration = offer.get("itineraries", [{}])[0].get("duration", "N/A")
        
        markdown_result += f"**Option {idx}: ₹{price}** | Duration: {duration}\n\n"
        
        for i_idx, itinerary in enumerate(offer.get("itineraries", [])):
            markdown_result += f"{'Outbound' if i_idx == 0 else 'Return'}: "
            
            segments = itinerary.get("segments", [])
            for seg_idx, seg in enumerate(segments):
                dep = seg.get("departure", {})
                arr = seg.get("arrival", {})
                carrier = seg.get("carrierCode", "N/A")
                
                dep_time = dep.get("at", "").split("T")[1][:5] if "T" in dep.get("at", "") else "N/A"
                arr_time = arr.get("at", "").split("T")[1][:5] if "T" in arr.get("at", "") else "N/A"
                
                markdown_result += f"{dep.get('iataCode', '')} {dep_time} → {arr.get('iataCode', '')} {arr_time}"
                
                if seg_idx < len(segments) - 1:
                    markdown_result += " | "
            
            markdown_result += "\n"
        
        markdown_result += "\n"
    
    return markdown_result

def format_hotel_results(data):
    if not data or "data" not in data or not data["data"]:
        return None

    markdown_result = "### 🏨 Hotel Options\n\n"
    
    for idx, hotel in enumerate(data["data"][:3], 1):  # Limit to top 3 hotels
        hotel_info = hotel.get("hotel", {})
        offers = hotel.get("offers", [])
        if not offers:
            continue
            
        offer = offers[0]
        price = offer.get("price", {}).get("total", "N/A")
        rating = hotel_info.get("rating", "N/A")
        name = hotel_info.get("name", "Unknown Hotel")
        
        markdown_result += f"**{name}** ({'⭐' * int(rating) if rating.isdigit() else rating})\n"
        markdown_result += f"Price: ₹{price} total | "
        markdown_result += f"Room: {offer.get('room', {}).get('typeEstimated', {}).get('category', 'Standard')}\n\n"
    
    return markdown_result

def gather_trip_results():
    # Search and organize results
    results = {}
    
    with st.spinner("Planning your perfect trip..."):
        token_data = asyncio.run(get_amadeus_token())
        if token_data:
            token = token_data.get("access_token")
            
            # Get flights
            payload = build_flight_payload(st.session_state.trip_details)
            flight_data = asyncio.run(search_flights(payload, token))
            results["flights"] = format_flight_results(flight_data)
            
            # Get hotels 
            if st.session_state.trip_details.get('destination'):
                check_in = st.session_state.trip_details['departure_date']
                
                # Set default check-out if not provided
                if st.session_state.trip_details.get('return_date'):
                    check_out = st.session_state.trip_details['return_date']
                else:
                    check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
                    check_out = (check_in_date + timedelta(days=3)).strftime("%Y-%m-%d")
                
                hotel_data = asyncio.run(search_hotels(
                    st.session_state.trip_details['destination'],
                    check_in,
                    check_out,
                    st.session_state.trip_details['travelers'],
                    token
                ))
                results["hotels"] = format_hotel_results(hotel_data)
        
        # Get recommendations
        if st.session_state.trip_details.get('destination'):
            dates = st.session_state.trip_details['departure_date']
            if st.session_state.trip_details.get('return_date'):
                dates += f" to {st.session_state.trip_details['return_date']}"
            else:
                dates += " onwards"
                
            recommendations = get_travel_recommendations(
                st.session_state.trip_details['destination'],
                dates
            )
            results["recommendations"] = recommendations
    
    return results

def show_trip_results():
    results = st.session_state.results
    
    # Create tabs for the results
    tab1, tab2, tab3 = st.tabs(["✈️ Flights", "🏨 Hotels", "🌴 Recommendations"])
    
    with tab1:
        if results.get("flights"):
            st.markdown(results["flights"])
        else:
            st.info("No flight options found for your search criteria. Try adjusting your dates or destinations.")
    
    with tab2:
        if results.get("hotels"):
            st.markdown(results["hotels"])
        else:
            st.info("No hotel options found for your search criteria.")
    
    with tab3:
        if results.get("recommendations"):
            st.markdown(results["recommendations"])
        else:
            st.info("Recommendations not available for this destination.")

def create_welcome_message():
    greetings = [
        "Hi there! I'm your travel assistant. Where are you dreaming of going?",
        "Hello! Ready to plan your next adventure? Where would you like to go?",
        "Welcome! I'd love to help you plan your perfect trip. What destination are you thinking about?",
        "Hey there, fellow traveler! What exciting destination can I help you explore?",
        "Hi! Let's plan something amazing. Where would you like to travel to?"
    ]
    return random.choice(greetings)

# --- Streamlit UI ---
st.set_page_config(
    page_title="Travel Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .chat-message {
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
        flex-direction: column;
    }
    .chat-message.user {
        background-color: #f0f7ff;
        border-left: 5px solid #2986cc;
    }
    .chat-message.assistant {
        background-color: #f9f9f9;
        border-left: 5px solid #7cc576;
    }
    .message-content {
        margin-left: 0.5rem;
    }
    .trip-summary {
        background-color: #f0f9ff;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        border-left: 5px solid #3b82f6;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f0f7ff;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #d1e7ff !important;
        border-bottom: 2px solid #1e88e5;
    }
</style>
""", unsafe_allow_html=True)

# App header with better styling
col1, col2 = st.columns([1, 3])
with col1:
    st.image("https://www.svgrepo.com/show/494078/travel-flight-tickets.svg", width=100)
with col2:
    st.title("✈️ Travel Planning Assistant")
    st.markdown("*Plan your perfect trip with personalized recommendations*")

# Sidebar for trip details summary if available
with st.sidebar:
    st.header("Your Trip Details")
    if st.session_state.trip_details.get("destination"):
        st.markdown(f"**Origin:** {st.session_state.trip_details['origin']}")
        st.markdown(f"**Destination:** {st.session_state.trip_details['destination']}")
        st.markdown(f"**Departure:** {st.session_state.trip_details['departure_date']}")
        if st.session_state.trip_details.get("return_date"):
            st.markdown(f"**Return:** {st.session_state.trip_details['return_date']}")
        st.markdown(f"**Travelers:** {st.session_state.trip_details['travelers']}")
        
        if st.button("Start a New Trip"):
            st.session_state.trip_details = {
                "origin": "",
                "destination": "",
                "departure_date": "",
                "return_date": "",
                "travelers": 1,
                "trip_type": "one-way"
            }
            st.session_state.current_step = "welcome"
            st.session_state.search_completed = False
            st.session_state.results = {
                "flights": None,
                "hotels": None, 
                "recommendations": None
            }
            st.session_state.conversation = []
            st.rerun()
    else:
        st.info("Start a conversation to plan your trip!")

# Initialize welcome message if first visit
if not st.session_state.conversation:
    welcome_msg = create_welcome_message()
    st.session_state.conversation.append({
        "role": "assistant",
        "content": welcome_msg
    })

# Display conversation
for msg in st.session_state.conversation:
    if msg["role"] == "user":
        st.markdown(f"""
        <div class="chat-message user">
            <div class="message-content">{msg["content"]}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="chat-message assistant">
            <div class="message-content">{msg["content"]}</div>
        </div>
        """, unsafe_allow_html=True)

# Show results if search is completed
if st.session_state.search_completed and st.session_state.results:
    show_trip_results()

# Get user input
with st.container():
    user_input = st.chat_input("Type your travel plans or questions here...")

if user_input:
    # Add user message to conversation
    st.session_state.conversation.append({"role": "user", "content": user_input})
    
    try:
        # Extract trip details regardless of what step we're in
        updated_details = extract_trip_details(user_input, st.session_state.trip_details)
        st.session_state.trip_details = updated_details
        
        # Check if we have enough details to search
        missing_details = check_missing_details(st.session_state.trip_details)
        
        if "new trip" in user_input.lower() or "start over" in user_input.lower():
            # Reset for new trip
            st.session_state.trip_details = {
                "origin": "",
                "destination": "",
                "departure_date": "",
                "return_date": "",
                "travelers": 1,
                "trip_type": "one-way"
            }
            st.session_state.current_step = "welcome"
            st.session_state.search_completed = False
            st.session_state.results = {
                "flights": None,
                "hotels": None,
                "recommendations": None
            }
            
            response = "Let's plan a new trip! Where would you like to go this time?"
            
        elif "search" in user_input.lower() or not missing_details:
            # If we have all details OR user explicitly asks to search
            if not missing_details:
                # Show trip summary
                summary = f"""I've got all your trip details:
- Flying from: {st.session_state.trip_details['origin']}
- Flying to: {st.session_state.trip_details['destination']}
- Departure: {st.session_state.trip_details['departure_date']}"""
                
                if st.session_state.trip_details.get('return_date'):
                    summary += f"\n- Return: {st.session_state.trip_details['return_date']}"
                
                summary += f"\n- Travelers: {st.session_state.trip_details['travelers']}"
                
                # Search for flights, hotels, and recommendations together
                st.session_state.results = gather_trip_results()
                st.session_state.search_completed = True
                
                # Generate combined response
                has_flights = st.session_state.results.get("flights") is not None
                has_hotels = st.session_state.results.get("hotels") is not None
                
                response = f"{summary}\n\nI've found some great options for your trip! "
                
                if has_flights and has_hotels:
                    response += "Check out the flight and hotel options in the tabs below. I've also included some recommendations for things to do at your destination!"
                elif has_flights:
                    response += "I found some flight options but couldn't find hotels for your dates. Take a look at the flights tab and my recommendations for your trip!"
                elif has_hotels:
                    response += "I found some hotels but couldn't find flight options for your dates. Take a look at the hotels tab and my recommendations for your trip!"
                else:
                    response += "I couldn't find flights or hotels matching your criteria. You might want to try different dates or destinations. I've still included some recommendations for your chosen destination!"
                
            else:
                # Need more details but user wants to search
                missing_field = missing_details[0]
                questions = {
                    "origin": "I need to know where you're flying from. Could you tell me the departure city?",
                    "destination": "Where would you like to go? Please let me know your destination.",
                    "departure_date": "When are you planning to leave? I need a departure date to find the best options.",
                    "return_date": "Since you're looking for a round trip, when would you like to return?"
                }
                response = questions.get(missing_field, "I need a few more details before I can search for you.")
        
        else:
            # Generate conversational response based on what we already know
            context = f"Trip details so far: {json.dumps(st.session_state.trip_details)}"
            response = generate_conversational_response(context, user_input)
            
            # Ask for specific missing detail if needed
            if missing_details:
                missing_field = missing_details[0]
                questions = {
                    "origin": "By the way, where will you be departing from?",
                    "destination": "And where are you heading to?",
                    "departure_date": "When are you planning to travel?",
                    "return_date": "And when would you like to return?" if st.session_state.trip_details.get("trip_type") == "round-trip" else ""
                }
                if questions.get(missing_field):
                    response += " " + questions.get(missing_field)
        
        # Add assistant response to conversation
        st.session_state.conversation.append({
            "role": "assistant",
            "content": response
        })
        
        # Rerun to update UI
        st.rerun()
        
    except Exception as e:
        # Handle errors gracefully
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "I'm having a bit of trouble understanding. Could you please rephrase your request? I'm looking for details like where you want to go and when you're planning to travel."
        })
        st.rerun()
