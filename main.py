import os
import json
import uuid
from datetime import date, timedelta
from typing import Optional, List
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()
app = FastAPI(title="Personalized Travel Itinerary Planner API", version="1.0.0")
origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin, "http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"]
)

trips = {}
supabase = None
if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    try:
        from supabase import create_client
        supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    except Exception as exc:
        print("Supabase unavailable; using in-memory storage:", exc)

class TripRequest(BaseModel):
    destination: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    budget: float = Field(gt=0, le=100000000)
    currency: str = "INR"
    travelers: int = Field(default=1, ge=1, le=100)
    interests: List[str] = []
    travel_style: str = "Balanced"
    accommodation: str = "Mid-range"
    notes: str = ""

class TripUpdate(BaseModel):
    title: Optional[str] = None
    itinerary: Optional[list] = None
    budget: Optional[float] = None

def days_between(start, end):
    return max(1, min((end - start).days + 1, 14))

def local_itinerary(req: TripRequest):
    count = days_between(req.start_date, req.end_date)
    interests = req.interests or ["Sightseeing", "Food"]
    destination = req.destination.strip()
    per_day = round(req.budget / count, 2)
    templates = [
        ("Arrival & local highlights", "Explore the central market and old town", "Visit a popular city landmark", "Try a well-rated local restaurant", "Walk or local cab"),
        ("Culture & hidden gems", "Visit a museum, heritage site, or cultural district", "Explore a local neighbourhood and craft market", "Enjoy regional street food", "Metro or local transport"),
        ("Nature & slow travel", "Start with a scenic viewpoint or garden", "Visit a nearby nature spot", "Relax at a café with local specialties", "Cab or public transport"),
        ("Food & experiences", "Take a local food walk", "Join a hands-on cultural activity", "Enjoy dinner near your stay", "Walk where possible"),
        ("Flexible exploration", "Choose a top-rated attraction matching your interests", "Explore a nearby landmark", "Try a popular local meal", "Local transport"),
    ]
    result = []
    for i in range(count):
        t = templates[i % len(templates)]
        result.append({
            "day": i + 1,
            "date": str(req.start_date + timedelta(days=i)),
            "theme": t[0],
            "activities": [
                {"time": "09:00", "title": t[1], "category": interests[i % len(interests)], "duration": "2 hours", "estimated_cost": round(per_day * .18, 2)},
                {"time": "12:30", "title": t[2], "category": "Sightseeing", "duration": "2 hours", "estimated_cost": round(per_day * .25, 2)},
                {"time": "15:30", "title": t[3], "category": "Food & leisure", "duration": "90 minutes", "estimated_cost": round(per_day * .22, 2)},
                {"time": "18:00", "title": f"Free time and dinner around {destination}", "category": "Dining", "duration": "2 hours", "estimated_cost": round(per_day * .2, 2)}
            ],
            "transport": t[4],
            "accommodation": f"{req.accommodation} accommodation near the main activity area",
            "estimated_cost": per_day
        })
    return result

async def ai_itinerary(req: TripRequest):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    prompt = f"""Create a practical travel itinerary in JSON only. Destination: {req.destination}. Dates: {req.start_date} to {req.end_date}. Budget: {req.currency} {req.budget} total for {req.travelers} traveller(s). Interests: {', '.join(req.interests)}. Style: {req.travel_style}. Accommodation: {req.accommodation}. Notes: {req.notes}.
Return object with title, summary, estimated_total, days array. Each day has day, date, theme, activities array (time,title,category,duration,estimated_cost), transport, accommodation, estimated_cost. Use realistic suggestions but do not claim live availability or exact opening hours."""
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "system", "content": "You are a careful travel planner. Output valid JSON only."}, {"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "temperature": 0.6}
        )
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])

def save_trip(trip):
    trips[trip["id"]] = trip
    if supabase:
        try:
            supabase.table("trips").upsert({
                "id": trip["id"], "title": trip["title"], "destination": trip["destination"],
                "start_date": trip["start_date"], "end_date": trip["end_date"], "budget": trip["budget"],
                "currency": trip["currency"], "travelers": trip["travelers"],
                "preferences": trip["preferences"], "itinerary": trip["itinerary"],
                "estimated_total": trip["estimated_total"]
            }).execute()
        except Exception as exc:
            print("Supabase save failed:", exc)

def all_trips():
    if supabase:
        try:
            rows = supabase.table("trips").select("*").order("created_at", desc=True).execute().data
            return rows
        except Exception as exc:
            print("Supabase read failed:", exc)
    return sorted(trips.values(), key=lambda x: x.get("created_at", ""), reverse=True)

@app.get("/")
def root():
    return {"message": "Personalized Travel Itinerary Planner API", "docs": "/docs", "status": "ok"}

@app.get("/api/health")
def health():
    return {"status": "ok", "ai_enabled": bool(os.getenv("OPENAI_API_KEY")), "supabase_enabled": supabase is not None}

@app.get("/api/trips")
def list_trips():
    return all_trips()

@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str):
    if trip_id in trips:
        return trips[trip_id]
    if supabase:
        try:
            rows = supabase.table("trips").select("*").eq("id", trip_id).limit(1).execute().data
            if rows: return rows[0]
        except Exception:
            pass
    raise HTTPException(404, "Trip not found")

@app.post("/api/trips")
async def create_trip(req: TripRequest):
    if req.end_date < req.start_date:
        raise HTTPException(400, "End date must be on or after start date.")
    generated = None
    try:
        generated = await ai_itinerary(req)
    except Exception as exc:
        print("AI generation failed; falling back to demo itinerary:", exc)
    itinerary = (generated or {}).get("days") or local_itinerary(req)
    total = (generated or {}).get("estimated_total") or sum(float(d.get("estimated_cost", 0)) for d in itinerary)
    title = (generated or {}).get("title") or f"{req.destination} getaway"
    trip = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "summary": (generated or {}).get("summary") or f"A {days_between(req.start_date, req.end_date)}-day {req.travel_style.lower()} trip tailored around {', '.join(req.interests) if req.interests else 'local highlights'}.",
        "destination": req.destination.strip(),
        "start_date": str(req.start_date), "end_date": str(req.end_date),
        "budget": req.budget, "currency": req.currency, "travelers": req.travelers,
        "preferences": {"interests": req.interests, "travel_style": req.travel_style, "accommodation": req.accommodation, "notes": req.notes},
        "itinerary": itinerary, "estimated_total": total,
        "created_at": date.today().isoformat()
    }
    save_trip(trip)
    return trip

@app.patch("/api/trips/{trip_id}")
def update_trip(trip_id: str, update: TripUpdate):
    trip = trips.get(trip_id)
    if not trip and supabase:
        try:
            rows = supabase.table("trips").select("*").eq("id", trip_id).limit(1).execute().data
            if rows: trip = rows[0]
        except Exception: pass
    if not trip:
        raise HTTPException(404, "Trip not found")
    data = update.model_dump(exclude_unset=True)
    trip.update(data)
    save_trip(trip)
    return trip

@app.post("/api/trips/{trip_id}/regenerate")
async def regenerate_trip(trip_id: str):
    trip = trips.get(trip_id)
    if not trip:
        raise HTTPException(404, "Trip not found in current session.")
    p = trip["preferences"]
    req = TripRequest(destination=trip["destination"], start_date=trip["start_date"], end_date=trip["end_date"], budget=trip["budget"], currency=trip["currency"], travelers=trip["travelers"], interests=p.get("interests", []), travel_style=p.get("travel_style", "Balanced"), accommodation=p.get("accommodation", "Mid-range"), notes=p.get("notes", ""))
    trip["itinerary"] = local_itinerary(req)
    trip["estimated_total"] = sum(float(d.get("estimated_cost", 0)) for d in trip["itinerary"])
    save_trip(trip)
    return trip
