# baksteenservice

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
| `definitie <woord>` | `definitie serendipiteit` | Woordenboekdefinitie |
| `apotheker <postcode>` | `apotheker 3000` | Wachtapotheek naam + tel |

## API Keys — secrets.py
```python
DEEPSEEK_API_KEY = "sk-..."    # https://platform.deepseek.com/
ORS_API_KEY      = "ors-..."   # https://openrouteservice.org/dev/#/home
OWM_API_KEY      = "owm-..."   # https://openweathermap.org/api (free, 1000/day)
```

## Dev mode
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```
