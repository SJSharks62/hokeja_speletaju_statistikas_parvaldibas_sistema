from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import webbrowser
from werkzeug.security import generate_password_hash, check_password_hash
import os

# Flask app inicializācija
app = Flask(__name__)
app.secret_key = "slepena_atslega"

# Datubāzes ceļš - fails database.db blakus skriptam
base_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(base_dir, 'database.db')

# Datubāzes savienojums
def iegut_savienojumu():
    sav = sqlite3.connect(db_path)
    sav.row_factory = sqlite3.Row
    return sav


# Tabulu izveide
def izveidot_tabulas():
    sav = iegut_savienojumu()
    cur = sav.cursor()

    # 1) Lietotāju tabula
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lietotaji (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lietotajvards TEXT UNIQUE NOT NULL,
            parole_hash TEXT NOT NULL,
            loma TEXT NOT NULL
        )
    """)

    # 2) Spēlētāju tabula
    cur.execute("""
        CREATE TABLE IF NOT EXISTS speletaji (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vards TEXT NOT NULL,
            numurs INTEGER NOT NULL,
            pozicija TEXT NOT NULL
        )
    """)

    # 3) Spēļu tabula
    cur.execute("""
        CREATE TABLE IF NOT EXISTS speles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datums TEXT NOT NULL,
            pretinieks TEXT NOT NULL
        )
    """)

    # 4) Spēlētāju statistika
    cur.execute("""
        CREATE TABLE IF NOT EXISTS statistika (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            speletaja_id INTEGER NOT NULL,
            speles_id INTEGER NOT NULL,
            varti INTEGER DEFAULT 0,
            piespeles INTEGER DEFAULT 0,
            soda_minutes INTEGER DEFAULT 0,
            metieni INTEGER DEFAULT 0,
            FOREIGN KEY (speletaja_id) REFERENCES speletaji(id),
            FOREIGN KEY (speles_id) REFERENCES speles(id)
        )
    """)

    # Noklusētais administrators (lietotājvārds: admin, parole: admin123)
    cur.execute("SELECT * FROM lietotaji WHERE lietotajvards = ?", ("admin",))
    if cur.fetchone() is None:
        parole_hash = generate_password_hash("admin123")
        cur.execute(
            "INSERT INTO lietotaji (lietotajvards, parole_hash, loma) VALUES (?, ?, ?)",
            ("admin", parole_hash, "Administrators")
        )

    sav.commit()
    sav.close()


# Lomu pārbaude
def prasa_lomu(*lomas):
    def dekorators(funkcija):
        def aploksne(*args, **kwargs):
            # 1) Vai lietotājs ir pieteicies?
            if "lietotajvards" not in session:
                flash("Nepieciešams pieteikties.", "br")
                return redirect(url_for("pieteiksanas"))
            # 2) Vai lietotājs ir atļautajā grupā?
            if session.get("loma") not in lomas:
                flash("Nav tiesību piekļūt šai sadaļai.", "br")
                return redirect(url_for("sakums"))
            return funkcija(*args, **kwargs)
        aploksne.__name__ = funkcija.__name__
        return aploksne
    return dekorators


# Sākumlapa
@app.route("/")
def sakums():
    if "lietotajvards" not in session:
        return redirect(url_for("pieteiksanas"))
    return render_template("dashboard.html")


# Pieteikšanās
@app.route("/login", methods=["GET", "POST"])
def pieteiksanas():
    if request.method == "POST":
        lietotajvards = request.form.get("lietotajvards")
        parole = request.form.get("parole")

        sav = iegut_savienojumu()
        cur = sav.cursor()
        cur.execute("SELECT * FROM lietotaji WHERE lietotajvards = ?", (lietotajvards,))
        lietotajs = cur.fetchone()
        sav.close()

        # Pārbauda paroli ar hash
        if lietotajs and check_password_hash(lietotajs["parole_hash"], parole):
            session["lietotajvards"] = lietotajs["lietotajvards"]
            session["loma"] = lietotajs["loma"]
            flash("Pieteikšanās veiksmīga.", "ok")
            return redirect(url_for("sakums"))
        else:
            flash("Nepareizs lietotājvārds vai parole.", "br")

    return render_template("login.html")


# Izrakstīšanās
@app.route("/logout")
def izrakstities():
    session.clear()
    flash("Esat izgājis no sistēmas.", "ok")
    return redirect(url_for("pieteiksanas"))


# Spēlētāju saraksts (pieejams visām lomām)
@app.route("/speletaji")
@prasa_lomu("Administrators", "Treneris", "Spēlētājs")
def speletaji():
    sav = iegut_savienojumu()
    cur = sav.cursor()

    sort = request.args.get("sort")

    sql = "SELECT * FROM speletaji"

    if sort == "vards":
        sql += " ORDER BY vards ASC"
    elif sort == "numurs":
        sql += " ORDER BY numurs ASC"
    elif sort == "pozicija":
        sql += " ORDER BY pozicija ASC"

    cur.execute(sql)
    speletaji = cur.fetchall()
    sav.close()

    return render_template("players.html", speletaji=speletaji)

# Jauna spēlētāja pievienošana (tikai admins/treneris)
@app.route("/speletaji/pievienot", methods=["GET", "POST"])
@prasa_lomu("Administrators", "Treneris")
def pievienot_speletaju():
    if request.method == "POST":
        vards = request.form.get("vards")
        numurs = request.form.get("numurs")
        pozicija = request.form.get("pozicija")

        if not vards or not numurs or not pozicija:
            flash("Jāaizpilda visi lauki.", "br")
            return redirect(url_for("pievienot_speletaju"))

        sav = iegut_savienojumu()
        cur = sav.cursor()
        cur.execute(
            "INSERT INTO speletaji (vards, numurs, pozicija) VALUES (?, ?, ?)",
            (vards, numurs, pozicija)
        )
        sav.commit()
        sav.close()
        flash("Spēlētājs pievienots.", "ok")
        return redirect(url_for("speletaji"))

    return render_template("player_form.html")

# Spēlētāju dzēšana (tikai admins) - dzēš arī saistīto statistiku
@app.route("/speletaji/<int:speletaja_id>/dzest", methods=["POST"])
@prasa_lomu("Administrators")
def dzest_speletaju(speletaja_id):
    sav = iegut_savienojumu()
    cur = sav.cursor()
    # Vispirms dzēšam statistiku, kas saistīta ar šo spēlētāju
    cur.execute("DELETE FROM statistika WHERE speletaja_id = ?", (speletaja_id,))
    # Tad pašu spēlētāju
    cur.execute("DELETE FROM speletaji WHERE id = ?", (speletaja_id,))
    sav.commit()
    sav.close()
    flash("Spēlētājs dzēsts.", "ok")
    return redirect(url_for("speletaji"))

# Spēlētāja rediģēšana (tikai admins)
@app.route("/speletaji/<int:speletaja_id>/rediget", methods=["GET", "POST"])
@prasa_lomu("Administrators")
def rediget_speletaju(speletaja_id):
    sav = iegut_savienojumu()
    cur = sav.cursor()

    if request.method == "POST":
        vards = request.form.get("vards")
        numurs = request.form.get("numurs")
        pozicija = request.form.get("pozicija")

        if not vards or not numurs or not pozicija:
            flash("Jāaizpilda visi lauki.", "br")
            return redirect(url_for("rediget_speletaju", speletaja_id=speletaja_id))

        cur.execute("""
            UPDATE speletaji
            SET vards = ?, numurs = ?, pozicija = ?
            WHERE id = ?
        """, (vards, numurs, pozicija, speletaja_id))
        sav.commit()
        sav.close()
        flash("Spēlētāja informācija atjaunināta.", "ok")
        return redirect(url_for("speletaji"))

    cur.execute("SELECT * FROM speletaji WHERE id = ?", (speletaja_id,))
    speletajs = cur.fetchone()
    sav.close()
    return render_template("player_edit.html", speletajs=speletajs)


# Spēļu saraksts (visām lomām)
@app.route("/speles")
@prasa_lomu("Administrators", "Treneris", "Spēlētājs")
def speles():
    sav = iegut_savienojumu()
    cur = sav.cursor()

    sort = request.args.get("sort")

    sql = "SELECT * FROM speles"

    if sort == "pretinieks":
        sql += " ORDER BY pretinieks ASC"
    elif sort == "datums":
        sql += " ORDER BY datums DESC"

    cur.execute(sql)
    speles = cur.fetchall()
    sav.close()

    return render_template("games.html", speles=speles)

# Jaunas spēles pievienošana (tikai admins/treneris)
@app.route("/speles/pievienot", methods=["GET", "POST"])
@prasa_lomu("Administrators", "Treneris")
def pievienot_speli():
    if request.method == "POST":
        datums = request.form.get("datums")
        pretinieks = request.form.get("pretinieks")

        if not datums or not pretinieks:
            flash("Jāaizpilda visi lauki.", "br")
            return redirect(url_for("pievienot_speli"))

        sav = iegut_savienojumu()
        cur = sav.cursor()
        cur.execute(
            "INSERT INTO speles (datums, pretinieks) VALUES (?, ?)",
            (datums, pretinieks)
        )
        sav.commit()
        sav.close()
        flash("Spēle pievienota.", "ok")
        return redirect(url_for("speles"))

    return render_template("game_form.html")

# Spēles dzēšana (tikai admins) - dzēš arī saistīto statistiku
@app.route("/speles/<int:speles_id>/dzest", methods=["POST"])
@prasa_lomu("Administrators")
def dzest_speli(speles_id):
    sav = iegut_savienojumu()
    cur = sav.cursor()
    # Vispirms dzēšam statistiku, kas saistīta ar šo spēli
    cur.execute("DELETE FROM statistika WHERE speles_id = ?", (speles_id,))
    # Tad pašu spēli
    cur.execute("DELETE FROM speles WHERE id = ?", (speles_id,))
    sav.commit()
    sav.close()
    flash("Spēle dzēsta.", "ok")
    return redirect(url_for("speles"))


# Spēlētāju statistika (ar filtrēšanu pēc spēlētāja/spēles)
@app.route("/statistika", methods=["GET", "POST"])
@prasa_lomu("Administrators", "Treneris", "Spēlētājs")
def statistika():
    sav = iegut_savienojumu()
    cur = sav.cursor()

    speletaja_id = request.args.get("speletaja_id")
    speles_id = request.args.get("speles_id")

    # Ielādē spēlētājus un spēles filtriem
    cur.execute("SELECT * FROM speletaji")
    speletaji = cur.fetchall()
    cur.execute("SELECT * FROM speles")
    speles = cur.fetchall()

    sql = """
        SELECT s.id, sp.vards, sp.numurs, sp.pozicija,
               g.datums, g.pretinieks,
               s.varti, s.piespeles, s.soda_minutes, s.metieni
        FROM statistika s
        JOIN speletaji sp ON s.speletaja_id = sp.id
        JOIN speles g ON s.speles_id = g.id
        WHERE 1=1
    """
    parametri = []

    if speletaja_id:
        sql += " AND s.speletaja_id = ?"
        parametri.append(speletaja_id)

    if speles_id:
        sql += " AND s.speles_id = ?"
        parametri.append(speles_id)

    cur.execute(sql, parametri)
    statistika_rindas = cur.fetchall()
    sav.close()

    return render_template(
        "stats.html",
        statistika=statistika_rindas,
        speletaji=speletaji,
        speles=speles,
        filtrs_speletaja_id=speletaja_id,
        filtrs_speles_id=speles_id
    )

# Statistikas ievade (tikai admins/treneris)
@app.route("/statistika/pievienot", methods=["GET", "POST"])
@prasa_lomu("Administrators", "Treneris")
def pievienot_statistiku():
    sav = iegut_savienojumu()
    cur = sav.cursor()
    cur.execute("SELECT * FROM speletaji")
    speletaji = cur.fetchall()
    cur.execute("SELECT * FROM speles WHERE datums <= DATE('now')")
    speles = cur.fetchall()

    if request.method == "POST":
        speletaja_id = request.form.get("speletaja_id")
        speles_id = request.form.get("speles_id")
        varti = request.form.get("varti") or 0
        piespeles = request.form.get("piespeles") or 0
        soda_minutes = request.form.get("soda_minutes") or 0
        metieni = request.form.get("metieni") or 0

        if not speletaja_id or not speles_id:
            flash("Jāizvēlas spēlētājs un spēle.", "br")
            return redirect(url_for("pievienot_statistiku"))

        cur.execute("""
            INSERT INTO statistika (speletaja_id, speles_id, varti, piespeles, soda_minutes, metieni)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (speletaja_id, speles_id, varti, piespeles, soda_minutes, metieni))
        sav.commit()
        sav.close()
        flash("Statistika pievienota.", "ok")
        return redirect(url_for("statistika"))

    sav.close()
    return render_template("stats_form.html", speletaji=speletaji, speles=speles)

# Statistikas dzēšana (tikai admins)
@app.route("/statistika/<int:id>/dzest", methods=["POST"])
@prasa_lomu("Administrators")
def dzest_statistiku(id):
    sav = iegut_savienojumu()
    cur = sav.cursor()
    cur.execute("DELETE FROM statistika WHERE id = ?", (id,))
    sav.commit()
    sav.close()
    flash("Statistikas ieraksts dzēsts.", "ok")
    return redirect(url_for("statistika"))


# Pārskats (kopējie rādītāji spēlētājiem)
@app.route("/parskati")
@prasa_lomu("Administrators", "Treneris", "Spēlētājs")
def parskati():
    sav = iegut_savienojumu()
    cur = sav.cursor()

    sort = request.args.get("sort")

    sql = """
        SELECT 
            sp.vards,
            sp.numurs,
            SUM(s.varti) AS varti,
            SUM(s.piespeles) AS piespeles,
            SUM(s.soda_minutes) AS soda_min,
            SUM(s.metieni) AS metieni
        FROM speletaji sp
        LEFT JOIN statistika s ON sp.id = s.speletaja_id
        GROUP BY sp.id
    """

    if sort in ["varti", "piespeles", "soda_min", "metieni"]:
        sql += f" ORDER BY {sort} DESC"

    cur.execute(sql)
    speletaju_parskats = cur.fetchall()
    sav.close()

    return render_template("reports.html", speletaju_parskats=speletaju_parskats)

# Mans Profils (paroles maiņa - administratoriem arī lietotājvārda maiņa)
@app.route("/profils", methods=["GET", "POST"])
@prasa_lomu("Administrators", "Treneris", "Spēlētājs")
def profils():
    sav = iegut_savienojumu()
    cur = sav.cursor()
    cur.execute("SELECT * FROM lietotaji WHERE lietotajvards = ?", (session["lietotajvards"],))
    lietotajs = cur.fetchone()

    if request.method == "POST":
        jaunais_lietotajvards = request.form.get("lietotajvards")
        veca_parole = request.form.get("veca_parole")
        jauna_parole = request.form.get("jauna_parole")

        if not check_password_hash(lietotajs["parole_hash"], veca_parole):
            flash("Vecā parole nav pareiza.", "br")
            return redirect(url_for("profils"))

        # Admins drīkst mainīt arī lietotājvārdu, citi – tikai paroli
        if session["loma"] == "Administrators" and jaunais_lietotajvards:
            cur.execute("UPDATE lietotaji SET lietotajvards = ? WHERE id = ?", (jaunais_lietotajvards, lietotajs["id"]))
            session["lietotajvards"] = jaunais_lietotajvards

        if jauna_parole:
            jauns_hash = generate_password_hash(jauna_parole)
            cur.execute("UPDATE lietotaji SET parole_hash = ? WHERE id = ?", (jauns_hash, lietotajs["id"]))

        sav.commit()
        sav.close()
        flash("Profils atjaunināts.", "ok")
        return redirect(url_for("sakums"))

    sav.close()
    return render_template("profile.html", lietotajs=lietotajs)

# Jauns lietotājs (tikai admins) - ļauj izveidot jaunu lietotāju.
@app.route("/lietotaji/pievienot", methods=["GET", "POST"])
@prasa_lomu("Administrators")
def pievienot_lietotaju():
    if request.method == "POST":
        lietotajvards = request.form.get("lietotajvards")
        parole = request.form.get("parole")
        loma = request.form.get("loma")

        if not lietotajvards or not parole or not loma:
            flash("Jāaizpilda visi lauki.", "br")
            return redirect(url_for("pievienot_lietotaju"))
        # Parole tiek šifrēta un saglabāta kā hash, nevis kā teksts.
        parole_hash = generate_password_hash(parole)
        sav = iegut_savienojumu()
        cur = sav.cursor()
        try:
            cur.execute(
                "INSERT INTO lietotaji (lietotajvards, parole_hash, loma) VALUES (?, ?, ?)",
                (lietotajvards, parole_hash, loma)
            )
            sav.commit()
            flash("Lietotājs izveidots. Nosūti viņam lietotājvārdu un paroli!", "ok")
        except sqlite3.IntegrityError:
            flash("Šāds lietotājvārds jau eksistē.", "br")
        sav.close()
        return redirect(url_for("pievienot_lietotaju"))

    return render_template("user_form.html")


# Palaist serveri (izveido tabulas un atver pārlūkā)
if __name__ == "__main__":
    izveidot_tabulas()
    webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=True)

