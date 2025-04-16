import streamlit as st
import asyncio
import aiohttp
import json
import google.generativeai as genai
from datetime import datetime, timedelta

# Initialize session state
if 'conversation' not in st.session_state:
    st.session_state.conversation = []
if 'trip_details' not in st.session_state:
    st.session_state.trip_details = {
        "origin": "",
        "destination": "",
        "departure_date": "",
        "return_date": "",
        "travelers": 1,
        "trip_type": "one-way"
    }
if 'awaiting_input' not in st.session_state:
    st.session_state.awaiting_input = None
if 'current_step' not in st.session_state:
    st.session_state.current_step = "trip_details"  # trip_details, flights, hotels, recommendations

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
                    st.error(f"Failed to get token: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        st.error(f"Token request failed: {str(e)}")
        return None

async def search_flights(payload, token):
    if not token:
        st.error("No valid token available")
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
                    st.error(f"Flight search failed: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        st.error(f"Flight search failed: {str(e)}")
        return None

async def search_hotels(city_code, check_in, check_out, token):  
    if not token:  
        st.error("No valid token available")  
        return None  
          
    url = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city"  
    params = {  
        'cityCode': city_code,  
        'radius': '5',  
        'radiusUnit': 'KM',  
        'includeClosed': 'false',  
        'bestRateOnly': 'true'  
    }  
      
    headers = {  
        'Authorization': f"Bearer {token}",  
        'Content-Type': 'application/json'  
    }  
      
    try:  
        async with aiohttp.ClientSession() as session:  
            async with session.get(url, headers=headers, params=params) as resp:  
                if resp.status != 200:  
                    st.error(f"Hotel search failed: {resp.status}")  
                    return None  
                hotels_data = await resp.json()  
                  
                if not hotels_data.get('data'):  
                    st.error("No hotels found for the provided city code.")  
                    return None  
                  
                hotel_ids = [hotel['hotelId'] for hotel in hotels_data['data']]  
                if not hotel_ids:  
                    st.error("No hotel IDs found in the response data.")  
                    return None  
                  
                offers_url = "https://test.api.amadeus.com/v3/shopping/hotel-offers"  
                offers_params = {  
                    'hotelIds': ','.join(hotel_ids[:5]),  
                    'adults': str(st.session_state.trip_details.get('travelers', 1)),  
                    'checkInDate': check_in,  
                    'checkOutDate': check_out,  
                    'roomQuantity': '1'  
                }  
                  
                async with session.get(offers_url, headers=headers, params=offers_params) as offers_resp:  
                    if offers_resp.status != 200:  
                        st.error(f"Hotel offers failed: {offers_resp.status}")  
                        return None  
                    return await offers_resp.json()  
    except Exception as e:  
        st.error(f"Hotel search failed: {str(e)}")  
        return None  
def get_travel_recommendations(destination, dates):
    prompt = f"""
    Provide travel recommendations for {destination} during {dates}. Include:
    1. Top 3 attractions to visit
    2. Local cuisine to try
    3. Cultural tips
    4. Packing suggestions
    5. Any seasonal events during {dates}
    
    Format your response with clear headings for each section.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Couldn't generate recommendations: {str(e)}"

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
        st.error(f"Extraction error: {str(e)}")
        return None

def check_missing_details(details):
    required_fields = ['origin', 'destination', 'departure_date']
    if details.get('trip_type', 'one-way') == 'round-trip':
        required_fields.append('return_date')
    missing = [field for field in required_fields if not details.get(field)]
    return missing

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
        st.error("No flights found matching your criteria.")
        return

    st.subheader("✈️ Flight Options")
    for offer in data["data"]:
        with st.expander(f"₹{offer.get('price', {}).get('grandTotal', 'N/A')} - {offer.get('itineraries', [{}])[0].get('duration', 'N/A')}"):
            price = offer.get("price", {}).get("grandTotal", "N/A")
            duration = offer.get("itineraries", [{}])[0].get("duration", "N/A")
            st.markdown(f"**Total Price:** ₹{price} | **Duration:** {duration}")
            
            for idx, itinerary in enumerate(offer.get("itineraries", [])):
                st.markdown(f"### {'Outbound' if idx == 0 else 'Return'} Flight")
                for seg in itinerary.get("segments", []):
                    dep = seg.get("departure", {})
                    arr = seg.get("arrival", {})
                    carrier = seg.get("carrierCode", "N/A")
                    flight_num = seg.get("number", "N/A")
                    st.markdown(
                        f"- **{dep.get('iataCode', '')} → {arr.get('iataCode', '')}**  \n"
                        f"  Flight: {carrier} {flight_num}  \n"
                        f"  Departure: {dep.get('at', 'N/A')}  \n"
                        f"  Arrival: {arr.get('at', 'N/A')}"
                    )
            st.markdown("---")

def show_hotel_results(data):
    if not data or "data" not in data or not data["data"]:
        st.error("No hotels found matching your criteria.")
        return

    st.subheader("🏨 Hotel Options")
    for hotel in data["data"]:
        hotel_info = hotel.get("hotel", {})
        offers = hotel.get("offers", [])
        if not offers:
            continue
            
        offer = offers[0]
        with st.expander(f"{hotel_info.get('name', 'Unknown Hotel')} - ₹{offer.get('price', {}).get('total', 'N/A')}"):
            st.markdown(f"**{hotel_info.get('name', 'Unknown Hotel')}**")
            st.markdown(f"**Rating:** {hotel_info.get('rating', 'N/A')}")
            st.markdown(f"**Address:** {hotel_info.get('address', {}).get('lines', [''])[0]}")
            st.markdown(f"**Price:** ₹{offer.get('price', {}).get('total', 'N/A')} (including taxes)")
            st.markdown(f"**Room Type:** {offer.get('room', {}).get('typeEstimated', {}).get('category', 'N/A')}")
            st.markdown(f"**Cancellation Policy:** {offer.get('policies', {}).get('cancellation', {}).get('description', 'N/A')}")
            st.markdown("---")

# --- Streamlit UI ---
st.set_page_config(page_title="Travel Assistant", layout="centered")
st.title("✈️🌴 Travel Planning Assistant")

# Display conversation history
for msg in st.session_state.conversation:
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    else:
        st.chat_message("assistant").write(msg["content"])

# Get user input
user_input = st.chat_input("Tell me about your travel plans...")

if user_input:
    # Add user message to conversation
    st.session_state.conversation.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    
    # Process based on current step
    if st.session_state.current_step == "trip_details":
        # Try to extract details
        with st.spinner("Analyzing your request..."):
            new_details = extract_trip_details(user_input)
            if new_details:
                # Update trip details
                for key in new_details:
                    if key in st.session_state.trip_details:
                        st.session_state.trip_details[key] = new_details[key]
                
                # Check for missing details
                missing = check_missing_details(st.session_state.trip_details)
                if missing:
                    next_field = missing[0]
                    questions = {
                        "origin": "Where are you flying from? (e.g., DEL for Delhi)",
                        "destination": "Where are you flying to? (e.g., BOM for Mumbai)",
                        "departure_date": "When are you departing? (e.g., 2025-05-15)",
                        "return_date": "When will you be returning? (e.g., 2025-05-22)",
                        "travelers": "How many travelers? (e.g., 2)"
                    }
                    question = questions.get(next_field, "")
                    st.session_state.awaiting_input = next_field
                    st.session_state.conversation.append({"role": "assistant", "content": question})
                    st.chat_message("assistant").write(question)
                else:
                    # All details collected
                    st.session_state.conversation.append({
                        "role": "assistant",
                        "content": f"Great! I have your trip details:\n\n"
                                  f"- From: {st.session_state.trip_details['origin']}\n"
                                  f"- To: {st.session_state.trip_details['destination']}\n"
                                  f"- Departure: {st.session_state.trip_details['departure_date']}\n"
                                  f"{'- Return: ' + st.session_state.trip_details['return_date'] + '\n' if st.session_state.trip_details.get('return_date') else ''}"
                                  f"- Travelers: {st.session_state.trip_details['travelers']}\n\n"
                                  "Would you like to:\n"
                                  "1. Search flights ✈️\n"
                                  "2. Find hotels 🏨\n"
                                  "3. Get travel recommendations 🌴"
                    })
                    st.chat_message("assistant").markdown(f"Great! I have your trip details:\n\n"
                                  f"- From: {st.session_state.trip_details['origin']}\n"
                                  f"- To: {st.session_state.trip_details['destination']}\n"
                                  f"- Departure: {st.session_state.trip_details['departure_date']}\n"
                                  f"{'- Return: ' + st.session_state.trip_details['return_date'] + '\n' if st.session_state.trip_details.get('return_date') else ''}"
                                  f"- Travelers: {st.session_state.trip_details['travelers']}\n\n"
                                  "Would you like to:\n"
                                  "1. Search flights ✈️\n"
                                  "2. Find hotels 🏨\n"
                                  "3. Get travel recommendations 🌴")
                    st.session_state.current_step = "actions"
            else:
                # Fallback to manual collection
                st.session_state.trip_details = {
                    "origin": "",
                    "destination": "",
                    "departure_date": "",
                    "return_date": "",
                    "travelers": 1,
                    "trip_type": "one-way"
                }
                question = "Where are you flying from? (e.g., DEL for Delhi)"
                st.session_state.awaiting_input = "origin"
                st.session_state.conversation.append({"role": "assistant", "content": question})
                st.chat_message("assistant").write(question)
    
    elif st.session_state.current_step == "actions":
        if "flight" in user_input.lower() or "1" in user_input:
            st.session_state.current_step = "flights"
            with st.spinner("Searching for flights..."):
                payload = build_flight_payload(st.session_state.trip_details)
                if payload:
                    token_data = asyncio.run(get_amadeus_token())
                    if token_data:
                        token = token_data.get("access_token")
                        flight_data = asyncio.run(search_flights(payload, token))
                        if flight_data:
                            st.session_state.conversation.append({
                                "role": "assistant",
                                "content": "Here are some flight options I found:"
                            })
                            st.chat_message("assistant").write("Here are some flight options I found:")
                            show_flight_results(flight_data)
            
            # Ask about next steps
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Would you also like to:\n1. Find hotels 🏨\n2. Get travel recommendations 🌴"
            })
            st.chat_message("assistant").markdown("Would you also like to:\n1. Find hotels 🏨\n2. Get travel recommendations 🌴")
        
        elif "hotel" in user_input.lower() or "2" in user_input:
            st.session_state.current_step = "hotels"
            check_in = st.session_state.trip_details['departure_date']
            check_out = st.session_state.trip_details['return_date'] if st.session_state.trip_details.get('return_date') else (
                datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
            
            with st.spinner("Searching for hotels..."):
                token_data = asyncio.run(get_amadeus_token())
                if token_data:
                    token = token_data.get("access_token")
                    hotel_data = asyncio.run(search_hotels(
                        st.session_state.trip_details['destination'],
                        check_in,
                        check_out,
                        token
                    ))
                    if hotel_data:
                        st.session_state.conversation.append({
                            "role": "assistant",
                            "content": "Here are some hotel options I found:"
                        })
                        st.chat_message("assistant").write("Here are some hotel options I found:")
                        show_hotel_results(hotel_data)
            
            # Ask about next steps
            st.session_state.conversation.append({
                "role": "assistant",
                "content": "Would you also like to:\n1. Get travel recommendations 🌴"
            })
            st.chat_message("assistant").markdown("Would you also like to:\n1. Get travel recommendations 🌴")
        
        elif "recommendation" in user_input.lower() or "3" in user_input:
            st.session_state.current_step = "recommendations"
            dates = st.session_state.trip_details['departure_date']
            if st.session_state.trip_details.get('return_date'):
                dates += " to " + st.session_state.trip_details['return_date']
            
            with st.spinner("Generating travel recommendations..."):
                recommendations = get_travel_recommendations(
                    st.session_state.trip_details['destination'],
                    dates
                )
                st.session_state.conversation.append({
                    "role": "assistant",
                    "content": f"Here are some recommendations for your trip to {st.session_state.trip_details['destination']}:"
                })
                st.chat_message("assistant").write(f"Here are some recommendations for your trip to {st.session_state.trip_details['destination']}:")
                st.markdown(recommendations)
    
    elif st.session_state.awaiting_input:
        field = st.session_state.awaiting_input
        st.session_state.trip_details[field] = user_input
        st.session_state.awaiting_input = None
        
        # Check if we have all required details
        missing = check_missing_details(st.session_state.trip_details)
        if missing:
            next_field = missing[0]
            questions = {
                "origin": "Where are you flying from? (e.g., DEL for Delhi)",
                "destination": "Where are you flying to? (e.g., BOM for Mumbai)",
                "departure_date": "When are you departing? (e.g., 2025-05-15)",
                "return_date": "When will you be returning? (e.g., 2025-05-22)",
                "travelers": "How many travelers? (e.g., 2)"
            }
            question = questions.get(next_field, "")
            st.session_state.awaiting_input = next_field
            st.session_state.conversation.append({"role": "assistant", "content": question})
            st.chat_message("assistant").write(question)
        else:
            # All details collected
            st.session_state.conversation.append({
                "role": "assistant",
                "content": f"Great! I have your trip details:\n\n"
                          f"- From: {st.session_state.trip_details['origin']}\n"
                          f"- To: {st.session_state.trip_details['destination']}\n"
                          f"- Departure: {st.session_state.trip_details['departure_date']}\n"
                          f"{'- Return: ' + st.session_state.trip_details['return_date'] + '\n' if st.session_state.trip_details.get('return_date') else ''}"
                          f"- Travelers: {st.session_state.trip_details['travelers']}\n\n"
                          "Would you like to:\n"
                          "1. Search flights ✈️\n"
                          "2. Find hotels 🏨\n"
                          "3. Get travel recommendations 🌴"
            })
            st.chat_message("assistant").markdown(f"Great! I have your trip details:\n\n"
                          f"- From: {st.session_state.trip_details['origin']}\n"
                          f"- To: {st.session_state.trip_details['destination']}\n"
                          f"- Departure: {st.session_state.trip_details['departure_date']}\n"
                          f"{'- Return: ' + st.session_state.trip_details['return_date'] + '\n' if st.session_state.trip_details.get('return_date') else ''}"
                          f"- Travelers: {st.session_state.trip_details['travelers']}\n\n"
                          "Would you like to:\n"
                          "1. Search flights ✈️\n"
                          "2. Find hotels 🏨\n"
                          "3. Get travel recommendations 🌴")
            st.session_state.current_step = "actions"

# Restart Conversation Button  
if st.button('Restart Conversation'):  
    st.session_state.con