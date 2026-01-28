import os

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import uuid, random
import socket
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

games = {}

# ------------------ REAL TAMBOLA TICKET GENERATOR ------------------
def generate_ticket():
    # Column ranges
    ranges = [
        list(range(1, 10)),    # 1-9
        list(range(10, 20)),   # 10-19
        list(range(20, 30)),   # 20-29
        list(range(30, 40)),   # 30-39
        list(range(40, 50)),   # 40-49
        list(range(50, 60)),   # 50-59
        list(range(60, 70)),   # 60-69
        list(range(70, 80)),   # 70-79
        list(range(80, 91)),   # 80-90
    ]

    # Step 1: Decide how many numbers per column
    col_counts = [1] * 9
    remaining = 15 - 9  # already placed 9

    while remaining > 0:
        c = random.randint(0, 8)
        if col_counts[c] < 3:
            col_counts[c] += 1
            remaining -= 1

    # Step 2: Pick numbers for each column
    columns = []
    for col in range(9):
        nums = sorted(random.sample(ranges[col], col_counts[col]))
        columns.append(nums)

    # Step 3: Empty 3x9 ticket
    ticket = [[None for _ in range(9)] for _ in range(3)]
    row_counts = [0, 0, 0]

    # Step 4: Place numbers ensuring each row has exactly 5
    for col in range(9):
        nums = columns[col][:]

        for num in nums:
            possible_rows = [
                r for r in range(3)
                if row_counts[r] < 5 and ticket[r][col] is None
            ]

            # Safety fallback (should rarely trigger)
            if not possible_rows:
                # restart generation if something went wrong
                return generate_ticket()

            r = random.choice(possible_rows)
            ticket[r][col] = num
            row_counts[r] += 1

    return ticket


# ------------------ ROUTES ------------------

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/host")
def host():
    game_id = str(uuid.uuid4())[:6]

    games[game_id] = {
        "players": {},
        "picked": [],
        "available": list(range(1,101)),
        "history": {"jaldi5":[], "row1":[], "row2":[],"row3":[], "full":[]}
    }

    # 👇 NEW: automatically get your local IP
    ip = get_local_ip()

    # 👇 Build invite link using that IP
    base = request.host_url.rstrip("/")
    invite_link = f"{base}/join/{game_id}"

    # 👇 Pass invite_link to template
    return render_template(
        "host.html",
        game_id=game_id,
        invite_link=invite_link
    )


@app.route("/join/<game_id>")
def join(game_id):
    return render_template("join.html", game_id=game_id)

# ✅ ADD THIS NEW ROUTE
@app.route("/player/<game_id>")
def player(game_id):
    return render_template("player.html", game_id=game_id)

# ------------------ SOCKET EVENTS ------------------

@socketio.on("join_game")
def join_game(data):
    game_id = data["game"]
    name = data["name"]

    pid = str(uuid.uuid4())[:6]
    ticket = generate_ticket()

    games[game_id]["players"][pid] = {
        "name": name,
        "ticket": ticket
    }

    join_room(game_id)

    # Send ticket to that player only
    emit("ticket", {"pid": pid, "ticket": ticket})

    # Send updated player list to everyone (host + players)
    emit(
        "players",
        [p["name"] for p in games[game_id]["players"].values()],
        room=game_id
    )


@socketio.on("pick")
def pick(data):
    game = games[data["game"]]
    if not game["available"]: return
    n = random.choice(game["available"])
    game["available"].remove(n)
    game["picked"].append(n)
    emit("number", n, room=data["game"])

@socketio.on("claim")
def claim(data):
    g = games[data["game"]]
    p = g["players"][data["pid"]]

    name = p["name"]
    ticket = p["ticket"]

    # Track what this player has already claimed
    claimed = p.setdefault("claimed", [])

    # These are the numbers player actually clicked
    marked = set(data.get("marked", []))

    # Flatten ticket
    flat = [n for r in ticket for n in r if n]

    # Validation rules
    valid = False
    ctype = data["type"]

    if ctype == "jaldi5" and len(marked) >= 5:
        valid = True

    elif ctype == "row1":
        valid = all(n in marked for n in ticket[0] if n)

    elif ctype == "row2":
        valid = all(n in marked for n in ticket[1] if n)

    elif ctype == "row3":
        valid = all(n in marked for n in ticket[2] if n)

    elif ctype == "full":
        valid = all(n in marked for n in flat)

    # Already claimed by this player
    if ctype in claimed:
        emit("invalid", room=request.sid)
        return

    if valid:
        claimed.append(ctype)

        if name not in g["history"][ctype]:
            g["history"][ctype].append(name)

        emit("history", g["history"], room=data["game"])
    else:
        emit("invalid", room=request.sid)


@app.route("/results/<game_id>")
def results(game_id):
    h = games[game_id]["history"]

    title_map = {
        "jaldi5": "Jaldi 5",
        "row1": "First Line",
        "row2": "Second Line",
        "row3": "Third Line",
        "full": "Full House"
    }

    text = "🎯 Tambola Game Results\n\n"

    for k, v in h.items():
        title = title_map[k]
        text += f"{title} Winners:\n"

        if not v:
            text += "None\n\n"
        else:
            for i, n in enumerate(v, 1):
                text += f"{i}. {n}\n"
            text += "\n"

    return text


@socketio.on("host_join")
def host_join(data):
    game_id = data["game"]
    join_room(game_id)



def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just forces OS to pick active interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip
# Add host='0.0.0.0'
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
