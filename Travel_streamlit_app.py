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
    if 'search_completed' not in st.session_state:
        st.session_state.search_completed = False
    if 'results' not in st.session_state:
        st.session_state.results = {
            "flights": None,
            "hotels": None,
            "recommendations": None
        }
    if 'airport_data' not in st.session_state:
        st.session_state.airport_data = {}

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
    "GOX": "Goa", # Alternative Goa code
    "IXG": "Belgaum",
    "JFK": "New York",
    "LHR": "London",
    "CDG": "Paris",
    "DXB": "Dubai",
    "SIN": "Singapore",
    "BKK": "Bangkok",
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
                    error = await resp.text()
                    return None
                return await resp.json()
    except Exception as e:
        return None

async def get_airport_info(iata_code, token):
    """Get more details about an airport by IATA code"""
    if not token or not iata_code:
        return None
    
    # Check if we already have this airport info cached
    if iata_code in st.session_state.airport_data:
        return st.session_state.airport_data[iata_code]
        
    url = f"https://test.api.amadeus.com/v1/reference-data/locations/{iata_code}"
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data and "data" in data:
                    # Cache the result
                    st.session_state.airport_data[iata_code] = data["data"]
                    return data["data"]
                return None
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
                    error_text = await resp.text()
                    print(f"Flight search error: {error_text}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"Exception in flight search: {str(e)}")
        return None

async def search_hotels(city_code, check_in, check_out, travelers, token):
    if not token:
        return None
    
    # Add debug info
    print(f"Searching hotels for {city_code} from {check_in} to {check_out}")
    
    # First get hotel IDs
    url = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city"
    params = {
        'cityCode': city_code,
        'radius': 10,  # Increased radius
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
        # Fallback to dummy data for demonstration
        # This would be replaced with actual API calls in production
        dummy_hotels = [
            {
                "hotel": {
                    "name": f"Beachside Resort {city_code}",
                    "rating": "4",
                    "address": {"lines": ["Beach Road, Calangute"]},
                    "hotelId": "DUMMY1"
                },
                "offers": [
                    {
                        "price": {"total": "12500"},
                        "room": {"typeEstimated": {"category": "Deluxe Room with Ocean View"}}
                    }
                ]
            },
            {
                "hotel": {
                    "name": f"City Center Hotel {city_code}",
                    "rating": "5",
                    "address": {"lines": ["Main Street, Panjim"]},
                    "hotelId": "DUMMY2"
                },
                "offers": [
                    {
                        "price": {"total": "18900"},
                        "room": {"typeEstimated": {"category": "Executive Suite"}}
                    }
                ]
            },
            {
                "hotel": {
                    "name": f"Palm Grove Resort {city_code}",
                    "rating": "3",
                    "address": {"lines": ["South Anjuna, North Goa"]},
                    "hotelId": "DUMMY3"
                },
                "offers": [
                    {
                        "price": {"total": "8750"},
                        "room": {"typeEstimated": {"category": "Standard Room with Garden View"}}
                    }
                ]
            }
        ]

        # Try the actual API first
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    hotels_data = await resp.json()
                    if hotels_data.get('data'):
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
                        
                        # Return real data if available
                        if all_offers:
                            return {"data": all_offers}
                
                # Fall back to dummy data if API fails or returns no results
                return {"data": dummy_hotels}
    except Exception as e:
        print(f"Exception in hotel search: {str(e)}")
        # Return dummy data on exception for demo purposes
        return {"data": dummy_hotels}

def format_duration(duration_str):
    """Convert API duration format (PT2H40M) to human-readable format (2h 40m)"""
    if not duration_str or not duration_str.startswith("PT"):
        return duration_str
    
    hours_match = re.search(r'(\d+)H', duration_str)
    minutes_match = re.search(r'(\d+)M', duration_str)
    
    hours = hours_match.group(1) if hours_match else "0"
    minutes = minutes_match.group(1) if minutes_match else "0"
    
    if hours == "0":
        return f"{minutes}m"
    else:
        return f"{hours}h {minutes}m"

def format_datetime(datetime_str):
    """Format API datetime (2025-05-05T17:35:00) to readable time (5:35 PM, May 5)"""
    if not datetime_str or "T" not in datetime_str:
        return datetime_str
    
    try:
        date_part, time_part = datetime_str.split("T")
        year, month, day = date_part.split("-")
        hour, minute, _ = time_part.split(":")
        
        # Convert to 12-hour format
        hour_int = int(hour)
        am_pm = "PM" if hour_int >= 12 else "AM"
        hour_12 = hour_int % 12
        if hour_12 == 0:
            hour_12 = 12
            
        # Get month name
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        month_name = month_names[int(month) - 1]
        
        return f"{hour_12}:{minute} {am_pm}, {month_name} {int(day)}"
    except:
        return datetime_str

def get_city_name(code):
    """Get city name from airport code"""
    return AIRPORT_CODES.get(code, code)

def get_travel_recommendations(destination, dates):
    city_name = get_city_name(destination)
    
    # Enhanced prompt for more engaging responses
    prompt = f"""
    Create engaging travel recommendations for {city_name} during {dates}. Include:
    
    1. A brief, enthusiastic intro about why {city_name} is special during this time
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
        return f"I'd love to tell you more about {city_name}, but I'm having trouble accessing that information right now."

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
    If the user mentions returning or a return journey, set trip_type to "round-trip".
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
                
        # If return is mentioned, ensure trip_type is round-trip
        if "return_date" in extracted_details and extracted_details["return_date"]:
            merged_details["trip_type"] = "round-trip"
                
        return merged_details
    except Exception as e:
        print(f"Error extracting trip details: {str(e)}")
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

async def format_flight_results(data, token):
    if not data or "data" not in data or not data["data"]:
        return None

    markdown_result = "### Your Flight Options\n\n"
    
    # Get airport information for better display
    origin_code = None
    destination_code = None
    
    for idx, offer in enumerate(data["data"][:3], 1):  # Limit to top 3 flights
        price = offer.get("price", {}).get("grandTotal", "N/A")
        
        # Outbound flight info
        outbound = offer.get("itineraries", [{}])[0]
        outbound_duration = format_duration(outbound.get("duration", "N/A"))
        
        outbound_segments = outbound.get("segments", [])
        if outbound_segments:
            first_seg = outbound_segments[0]
            last_seg = outbound_segments[-1]
            
            origin_code = first_seg.get("departure", {}).get("iataCode")
            destination_code = last_seg.get("arrival", {}).get("iataCode")
            
            dep_datetime = first_seg.get("departure", {}).get("at")
            arr_datetime = last_seg.get("arrival", {}).get("at")
            
            origin_city = get_city_name(origin_code)
            destination_city = get_city_name(destination_code)
            
            # Format times for display
            dep_time = dep_datetime.split("T")[1][:5] if dep_datetime and "T" in dep_datetime else "N/A"
            arr_time = arr_datetime.split("T")[1][:5] if arr_datetime and "T" in arr_datetime else "N/A"
            
            # Format dates
            dep_date = format_datetime(dep_datetime)
            arr_date = format_datetime(arr_datetime)
            
            airline = first_seg.get("carrierCode", "")
            
            # Flight option header
            markdown_result += f"#### Option {idx}: ₹{price}\n"
            markdown_result += f"**{origin_city} to {destination_city}** • {outbound_duration} • {airline}\n\n"
            
            # Departure and arrival details
            markdown_result += f"**Depart:** {dep_time} ({origin_code}), {dep_date}\n"
            markdown_result += f"**Arrive:** {arr_time} ({destination_code}), {arr_date}\n"
            
            # Add connection info if there are multiple segments
            if len(outbound_segments) > 1:
                markdown_result += f"**Connections:** {len(outbound_segments)-1}\n"
        
        # Return flight info (if available)
        if len(offer.get("itineraries", [])) > 1:
            inbound = offer.get("itineraries", [{}])[1]
            inbound_duration = format_duration(inbound.get("duration", "N/A"))
            
            inbound_segments = inbound.get("segments", [])
            if inbound_segments:
                first_seg = inbound_segments[0]
                last_seg = inbound_segments[-1]
                
                dep_datetime = first_seg.get("departure", {}).get("at")
                arr_datetime = last_seg.get("arrival", {}).get("at")
                
                # Swap cities for return
                origin_city, destination_city = destination_city, origin_city
                origin_code, destination_code = destination_code, origin_code
                
                # Format times for display
                dep_time = dep_datetime.split("T")[1][:5] if dep_datetime and "T" in dep_datetime else "N/A"
                arr_time = arr_datetime.split("T")[1][:5] if arr_datetime and "T" in arr_datetime else "N/A"
                
                # Format dates
                dep_date = format_datetime(dep_datetime)
                arr_date = format_datetime(arr_datetime)
                
                airline = first_seg.get("carrierCode", "")
                
                markdown_result += f"\n**Return: {origin_city} to {destination_city}** • {inbound_duration} • {airline}\n\n"
                
                # Departure and arrival details
                markdown_result += f"**Depart:** {dep_time} ({origin_code}), {dep_date}\n"
                markdown_result += f"**Arrive:** {arr_time} ({destination_code}), {arr_date}\n"
                
                # Add connection info if there are multiple segments
                if len(inbound_segments) > 1:
                    markdown_result += f"**Connections:** {len(inbound_segments)-1}\n"
        
        markdown_result += "\n---\n\n"
    
    return markdown_result

def format_hotel_results(data):
    if not data or "data" not in data or not data["data"]:
        return None

    markdown_result = "### Your Hotel Options\n\n"
    
    for idx, hotel in enumerate(data["data"][:3], 1):  # Limit to top 3 hotels
        hotel_info = hotel.get("hotel", {})
        offers = hotel.get("offers", [])
        if not offers:
            continue
            
        offer = offers[0]
        price = offer.get("price", {}).get("total", "N/A")
        rating = hotel_info.get("rating", "N/A")
        name = hotel_info.get("name", "Unknown Hotel")
        address = hotel_info.get("address", {}).get("lines", [""])[0]
        room_type = offer.get("room", {}).get("typeEstimated", {}).get("category", "Standard Room")
        
        # Calculate stars display
        stars = "⭐" * int(rating) if rating and rating.isdigit() else ""
        
        markdown_result += f"#### {name} {stars}\n"
        markdown_result += f"**Price:** ₹{price} total\n"
        markdown_result += f"**Room Type:** {room_type}\n"
        markdown_result += f"**Address:** {address}\n"
        
        # Add some amenities (dummy data for demo)
        amenities = ["Free WiFi", "Swimming Pool", "Restaurant", "Room Service"]
        random.shuffle(amenities)
        markdown_result += f"**Amenities:** {', '.join(amenities[:3])}\n\n"
        
        markdown_result += "---\n\n"
    
    return markdown_result

async def gather_trip_results():
    # Search and organize results
    results = {}
    
    token_data = await get_amadeus_token()
    if token_data:
        token = token_data.get("access_token")
        
        # Get flights
        payload = build_flight_payload(st.session_state.trip_details)
        flight_data = await search_flights(payload, token)
        results["flights"] = await format_flight_results(flight_data, token)
        
        # Get hotels 
        if st.session_state.trip_details.get('destination'):
            check_in = st.session_state.trip_details['departure_date']
            
            # Set default check-out if not provided
            if st.session_state.trip_details.get('return_date'):
                check_out = st.session_state.trip_details['return_date']
            else:
                check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
                check_out = (check_in_date + timedelta(days=3)).strftime("%Y-%m-%d")
            
            hotel_data = await search_hotels(
                st.session_state.trip_details['destination'],
                check_in,
                check_out,
                st.session_state.trip_details['travelers'],
                token
            )
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
    tab1, tab2, tab3 = st.tabs(["✈️ Flights", "🏨 Hotels", "🌴 Things to Do"])
    
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
    .highlight-box {
        background-color: #f0f9ff;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #3b82f6;
        margin-bottom: 20px;
    }
    .st-emotion-cache-1gulkj5 {
        background-color: #fafafa;
        border-radius: 10px;
        padding: 20px;
    }
</style>
""", unsafe_allow_html=True)

# App header with better styling
col1, col2 = st.columns([1, 4])
with col1:
    st.image("https://www.svgrepo.com/show/494078/travel-flight-tickets.svg", width=100)
with col2:
    st.title("✈️ Travel Planning Assistant")
    st.markdown("*Your personal travel companion - flights, hotels, and recommendations all in one place*")

# Sidebar for trip details summary if available
with st.sidebar:
    st.header("Your Trip Details")
    if st.session_state.trip_details.get("destination"):
        st.markdown(f"**From:** {get_city_name(st.session_state.trip_details['origin'])} ({st.session_state.trip_details['origin']})")
        st.markdown(f"**To:** {get_city_name(st.session_state.trip_details['destination'])} ({st.session_state.trip_details['destination']})")
        st.markdown(f"**Departure:** {st.session_state.trip_details['departure_date']}")
        if st.session_state.trip_details.get("return_date"):
            st.markdown(f"**Return:** {st.session_state.trip_details['return_date']}")
        st.markdown(f"**Travelers:** {st.session_state.trip_details['travelers']}")
        st.markdown(f"**Trip Type:** {st.session_state.trip_details['trip_type'].title()}")
        
        if st.button("Start a New Trip"):
            st.session_state.trip_details = {
                "origin": "",
                "destination": "",
                "
