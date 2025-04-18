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

# Updated image sources using reliable alternatives
AIRLINE_LOGOS = {
    "AI": "https://www.airindia.com/content/dam/airindia/logos/Air-India-Logo.png",
    "6E": "https://www.indigoair.com/images/indigo-logo.svg",
    "UK": "https://www.airvistara.com/resources/images/logo.svg",
    "SG": "https://www.spicejet.com/images/logo.svg",
    "default": "https://cdn-icons-png.flaticon.com/512/1169/1169168.png"
}

HOTEL_CHAINS = {
    "Marriott": "https://logos-world.net/wp-content/uploads/2021/08/Marriott-Logo.png",
    "Hilton": "https://logos-world.net/wp-content/uploads/2021/02/Hilton-Logo.png",
    "Hyatt": "https://logos-world.net/wp-content/uploads/2021/11/Hyatt-Logo.png",
    "Taj": "https://seeklogo.com/images/T/Taj_Hotels-logo-8D9C5AEC1F-seeklogo.com.png",
    "default": "https://cdn-icons-png.flaticon.com/512/2969/2969446.png"
}

PARTNER_LOGOS = [
    {"name": "Air India", "url": "https://www.airindia.com/content/dam/airindia/logos/Air-India-Logo.png"},
    {"name": "IndiGo", "url": "https://www.indigoair.com/images/indigo-logo.svg"},
    {"name": "Vistara", "url": "https://www.airvistara.com/resources/images/logo.svg"},
    {"name": "Marriott", "url": "https://logos-world.net/wp-content/uploads/2021/08/Marriott-Logo.png"},
    {"name": "Hyatt", "url": "https://logos-world.net/wp-content/uploads/2021/11/Hyatt-Logo.png"}
]

# Airport codes mapping
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
</style>
""", unsafe_allow_html=True)

# [All your helper functions remain exactly the same...]

# Header with gradient
st.markdown("""
<div class="header">
    <h1 style="color:white; margin:0;">✈️ TravelEase Assistant</h1>
    <p style="color:white; margin:0;">Your personal travel planning companion</p>
</div>
""", unsafe_allow_html=True)

# Partner logos - Using official websites and reliable sources
st.markdown("### Our Travel Partners")

cols = st.columns(len(PARTNER_LOGOS))
for i, partner in enumerate(PARTNER_LOGOS):
    with cols[i]:
        try:
            st.image(
                partner["url"],
                width=80,
                caption=partner["name"]
            )
        except:
            st.markdown(f"**{partner['name']}**")
            st.image(
                "https://cdn-icons-png.flaticon.com/512/1169/1169168.png",
                width=60,
                caption="Partner Logo"
            )

# [Rest of your Streamlit UI code remains the same, but will now use the updated AIRLINE_LOGOS and HOTEL_CHAINS]

# Display conversation
for msg in st.session_state.conversation:
    st.markdown(f"""
    <div class="{'user' if msg['role']=='user' else 'assistant'}-message">
        {msg["content"]}
    </div>
    """, unsafe_allow_html=True)

# User input
if user_input := st.chat_input("Where would you like to travel?", key="chat_input"):
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
            st.info("No flights found")
    
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

# Loading indicator
if st.session_state.search_in_progress:
    st.spinner("Finding the best options...")
