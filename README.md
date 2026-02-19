# baksteenservice
Ik zit te veel op mijn smartphone dus ik wou terug naar een baksteen. Een goeie tien jaar geleden leerde ik door mond tot mond reclame de OG baksteenservice kennen. Ik kon treinuren opzoeken, wikipedia raadplegen met mijn oude nokia. Nu blijkt de service niet meer te bestaan dus zet ik het zelf weer op.

simkaart en simlezer zijn onderweg dus het is nog niet live. Als het live wordt zet ik hier het telefoonnummer.


## Commands

| SMS | Voorbeeld | Antwoord |
|-----|-----------|----------|
| `gpt <tekst>` | `gpt wat is kwantumverstrengeling` | Max 160 chars |
| `janee <vraag>` | `janee is kip lekkerder dan rund` | `Ja` / `Nee` |
| `trein <v> <a> [u]` | `trein leuven brussel 17` | Volgende 3 treinen |
| `route <van> NAAR <naar>` | `route marktplein tienen NAAR leuven station` | Stap-voor-stap |
| `weer <stad>` | `weer leuven` | Temp, beschrijving, wind |
| `nieuws` | `nieuws` | Top 3 VRT NWS koppen |
| `vertaling <taal> <tekst>` | `vertaling en fiets` | `fiets → bicycle` |
| `apotheker <postcode>` | `apotheker 3000` | Wachtapotheek adres + tel |


## Dev mode
De structuur is alsvolgt: 
listener.py luistert naar inkomende berichten,
analyser.py extraheert de command en variabelen, 
action.py behandelt de command en doet de nodige bewerkingen achter de schermen (API calls, scraping, vormen van de terug stuur sms), 
returner.py stuurt de sms terug.
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
