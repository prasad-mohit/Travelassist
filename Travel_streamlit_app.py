import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta

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
    prompt = f"""
    Provide travel recommendations for {destination} during {dates}. Include:
    - Top attractions to visit
    - Local cuisine to try
    - Cultural tips
    - Packing suggestions
    - Any seasonal events
    
    Keep the response conversational and friendly.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"I'd love to tell you more about {destination}, but I'm having trouble accessing that information right now."

def extract_trip_details(user_input):
    prompt = f"""
    Analyze this travel request and extract details:
    "{user_input}"
    
    Return JSON with any details you can find from this list:
    - origin (IATA code)
    - destination (IATA code)
    - departure_date (YYYY-MM-DD)
    - return_date (YYYY-MM-DD) if round trip
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
    
    Return ONLY the JSON object. If any field is missing, omit it.
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

def show_flight_results(data):
    if not data or "data" not in data or not data["data"]:
        st.error("I couldn't find any flights matching your criteria. Let me know if you'd like to try different dates.")
        return

    st.subheader("Here are some flight options I found:")
    for offer in data["data"]:
        with st.expander(f"Flight for ₹{offer.get('price', {}).get('grandTotal', 'N/A')}"):
            price = offer.get("price", {}).get("grandTotal", "N/A")
            duration = offer.get("itineraries", [{}])[0].get("duration", "N/A")
            st.markdown(f"**Price:** ₹{price} | **Duration:** {duration}")
            
            for idx, itinerary in enumerate(offer.get("itineraries", [])):
                st.markdown(f"### {'Outbound' if idx == 0 else 'Return'} Flight")
                for seg in itinerary.get("segments", []):
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})
                    carrier = seg.get("carrierCode", "N/A")
                    flight_num = seg.get("number", "N/A")
                    st.markdown(
                        f"- **{dep.get('iataCode', '')} → {arr.get('iataCode', '')}**  \n"
                        f"  {carrier} {flight_num}  \n"
                        f"  Departure: {dep.get('at', 'N/A')}  \n"
                        f"  Arrival: {arr.get('at', 'N/A')}"
                    )
            st.markdown("---")

def show_hotel_results(data):
    if not data or "data" not in data or not data["data"]:
        st.error("I couldn't find any hotels matching your criteria. Would you like to try different dates?")
        return

    st.subheader("Here are some hotel options:")
    for hotel in data["data"]:
        hotel_info = hotel.get("hotel", {})
        offers = hotel.get("offers", [])
        if not offers:
            continue
            
        offer = offers[0]
        with st.expander(f"{hotel_info.get('name', 'Unknown Hotel')} - ₹{offer.get('price', {}).get('total', 'N/A')}/night"):
            st.markdown(f"**{hotel_info.get('name', 'Unknown Hotel')}**")
            st.markdown(f"**Rating:** {hotel_info.get('rating', 'N/A')}")
            st.markdown(f"**Address:** {hotel_info.get('address', {}).get('lines', [''])[0]}")
            st.markdown(f"**Price:** ₹{offer.get('price', {}).get('total', 'N/A')} total for your stay")
            st.markdown(f"**Room Type:** {offer.get('room', {}).get('typeEstimated', {}).get('category', 'N/A')}")
            st.markdown("---")

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

if user_input:
    # Add user message to conversation
    st.session_state.conversation.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    
    try:
        if st.session_state.current_step == "welcome":
            # Initial greeting and trip details collection
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Great! I'd be happy to help plan your trip. Could you tell me more about your travel plans? For example: \n\n\"I want to fly from Delhi to Goa on May 5th with 6 people\""
            })
            st.chat_message("assistant").write("Great! I'd be happy to help plan your trip. Could you tell me more about your travel plans? For example: \n\n\"I want to fly from Delhi to Goa on May 5th with 6 people\"")
            st.session_state.current_step = "collect_details"
        
        elif st.session_state.current_step == "collect_details":
            # Extract trip details from user input
            with st.spinner("Analyzing your trip details..."):
                new_details = extract_trip_details(user_input)
                if new_details:
                    # Update trip details
                    for key in new_details:
                        if key in st.session_state.trip_details:
                            st.session_state.trip_details[key] = new_details[key]
                    
                    # Check for missing details
                    missing = check_missing_details(st.session_state.trip_details)
                    if missing:
                        questions = {
                            "origin": "Which city will you be flying from? (e.g., DEL for Delhi)",
                            "destination": "Which city are you traveling to? (e.g., GOI for Goa)",
                            "departure_date": "When are you planning to depart? (e.g., 2024-05-05)",
                            "return_date": "When will you be returning? (e.g., 2024-05-12)",
                            "travelers": "How many people will be traveling?"
                        }
                        question = questions.get(missing[0], "")
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": question
                        })
                        st.chat_message("assistant").write(question)
                    else:
                        # All details collected - proceed to next steps
                        st.session_state.trip_details['hotel_check_in'] = st.session_state.trip_details['departure_date']
                        if st.session_state.trip_details.get('return_date'):
                            st.session_state.trip_details['hotel_check_out'] = st.session_state.trip_details['return_date']
                        else:
                            # Default to 3 nights if no return date
                            check_in = datetime.strptime(st.session_state.trip_details['departure_date'], "%Y-%m-%d")
                            st.session_state.trip_details['hotel_check_out'] = (check_in + timedelta(days=3)).strftime("%Y-%m-%d")
                        
                        # Show summary and automatically proceed to flights
                        summary = f"""I have your trip details:
- Flying from: {st.session_state.trip_details['origin']}
- Flying to: {st.session_state.trip_details['destination']}
- Departure: {st.session_state.trip_details['departure_date']}"""
                        
                        if st.session_state.trip_details.get('return_date'):
                            summary += f"\n- Return: {st.session_state.trip_details['return_date']}"
                        
                        summary += f"\n- Travelers: {st.session_state.trip_details['travelers']}"
                        
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": summary + "\n\nLet me find some flight options for you..."
                        })
                        st.chat_message("assistant").markdown(summary + "\n\nLet me find some flight options for you...")
                        st.session_state.current_step = "search_flights"
                        st.rerun()
                else:
                    # Couldn't extract details - ask for clarification
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": "I couldn't quite understand your travel plans. Could you please tell me again where and when you're traveling? For example: \n\n\"I want to go to Goa from Delhi on May 5th with 6 people\""
                    })
                    st.chat_message("assistant").write("I couldn't quite understand your travel plans. Could you please tell me again where and when you're traveling? For example: \n\n\"I want to go to Goa from Delhi on May 5th with 6 people\"")
        
        elif st.session_state.current_step == "search_flights":
            # Search for flights
            with st.spinner("Searching for flight options..."):
                payload = build_flight_payload(st.session_state.trip_details)
                token_data = asyncio.run(get_amadeus_token())
                if token_data:
                    token = token_data.get("access_token")
                    flight_data = asyncio.run(search_flights(payload, token))
                    
                    if flight_data:
                        show_flight_results(flight_data)
                        
                        # Automatically proceed to hotels
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": "Now let me find some hotel options for your stay..."
                        })
                        st.chat_message("assistant").write("Now let me find some hotel options for your stay...")
                        st.session_state.current_step = "search_hotels"
                        st.rerun()
                    else:
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": "I couldn't find any flights for those dates. Would you like to try different travel dates?"
                        })
                        st.chat_message("assistant").write("I couldn't find any flights for those dates. Would you like to try different travel dates?")
                        st.session_state.current_step = "collect_details"
                else:
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": "I'm having trouble accessing flight information right now. Let me try to find hotels instead."
                    })
                    st.chat_message("assistant").write("I'm having trouble accessing flight information right now. Let me try to find hotels instead.")
                    st.session_state.current_step = "search_hotels"
                    st.rerun()
        
        elif st.session_state.current_step == "search_hotels":
            # Search for hotels
            with st.spinner("Searching for hotel options..."):
                token_data = asyncio.run(get_amadeus_token())
                if token_data:
                    token = token_data.get("access_token")
                    hotel_data = asyncio.run(search_hotels(
                        st.session_state.trip_details['destination'],
                        st.session_state.trip_details['hotel_check_in'],
                        st.session_state.trip_details['hotel_check_out'],
                        st.session_state.trip_details['travelers'],
                        token
                    ))
                    
                    if hotel_data:
                        show_hotel_results(hotel_data)
                        
                        # Automatically proceed to recommendations
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": f"Would you like some recommendations for things to do in {st.session_state.trip_details['destination']} during your stay?"
                        })
                        st.chat_message("assistant").write(f"Would you like some recommendations for things to do in {st.session_state.trip_details['destination']} during your stay?")
                        st.session_state.current_step = "offer_recommendations"
                    else:
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": "I couldn't find any hotels for those dates. Would you like to try different dates?"
                        })
                        st.chat_message("assistant").write("I couldn't find any hotels for those dates. Would you like to try different dates?")
                        st.session_state.current_step = "collect_details"
                else:
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": f"Would you like some recommendations for things to do in {st.session_state.trip_details['destination']} during your stay?"
                    })
                    st.chat_message("assistant").write(f"Would you like some recommendations for things to do in {st.session_state.trip_details['destination']} during your stay?")
                    st.session_state.current_step = "offer_recommendations"
        
        elif st.session_state.current_step == "offer_recommendations":
            if "yes" in user_input.lower() or "recommendation" in user_input.lower():
                # Generate recommendations
                dates = st.session_state.trip_details['departure_date']
                if st.session_state.trip_details.get('return_date'):
                    dates += f" to {st.session_state.trip_details['return_date']}"
                
                with st.spinner(f"Finding great things to do in {st.session_state.trip_details['destination']}..."):
                    recommendations = get_travel_recommendations(
                        st.session_state.trip_details['destination'],
                        dates
                    )
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": f"Here are some recommendations for your trip to {st.session_state.trip_details['destination']}:\n\n{recommendations}"
                    })
                    st.chat_message("assistant").markdown(f"Here are some recommendations for your trip to {st.session_state.trip_details['destination']}:\n\n{recommendations}")
                
                # Offer to plan another trip
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Is there anything else I can help you with for this trip? Or would you like to plan another trip?"
                })
                st.chat_message("assistant").write("Is there anything else I can help you with for this trip? Or would you like to plan another trip?")
                st.session_state.current_step = "follow_up"
            else:
                # Skip recommendations
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Is there anything else I can help you with for this trip? Or would you like to plan another trip?"
                })
                st.chat_message("assistant").write("Is there anything else I can help you with for this trip? Or would you like to plan another trip?")
                st.session_state.current_step = "follow_up"
        
        elif st.session_state.current_step == "follow_up":
            if "another" in user_input.lower() or "new" in user_input.lower():
                # Start over
                init_session_state()
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "Great! Where would you like to go this time?"
                })
                st.chat_message("assistant").write("Great! Where would you like to go this time?")
                st.rerun()
            else:
                # Assume they want to modify current trip
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": "What would you like to change about your trip? You can modify dates, destination, or number of travelers."
                })
                st.chat_message("assistant").write("What would you like to change about your trip? You can modify dates, destination, or number of travelers.")
                st.session_state.current_step = "collect_details"
    
    except Exception as e:
        st.session_state.conversation.append({
            "role": "assistant",
            "content": "Sorry, I encountered an issue. Let's continue our conversation."
        })
        st.chat_message("assistant").write("Sorry, I encountered an issue. Let's continue our conversation.")
        st.session_state.current_step = "follow_up"
