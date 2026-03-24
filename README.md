
### Config
- Riot Game API KEY = https://developer.riotgames.com
- Django KEY = "your project key.."
- RIOT DD VERSION = 'most recent dd verison'
- DEBUG -> normally False
- EMAIL_HOST = 'smtp.google.com'
- EMAIL_HOST_USER = 'your Gmail'
- EMAIL_HOST_PASSWORD = 'password (not your gmail password)'
- DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

### about deai.gg

deai.gg is a test web platform that supports party recruitment and match history lookup for Riot Games titles such as League of Legends, VALORANT, and Teamfight Tactics.

At this time, VALORANT is not yet supported because it requires approval for the Riot Games API as well as an RSO application.

Currently, I have implemented the basic structure for match history lookup for League of Legends and Teamfight Tactics using other Riot Games APIs. Additionally, I have created pages that provide both general and detailed information (such as items, synergies, champions, weapons, etc) for all three games: League of Legends, Teamfight Tactics, and VALORANT. Since access to VALORANT data is limited, so I used an alternative API (valorant-api) to build the VALORANT-related information pages.

deai.gg is still in the preparation. If I am granted a Production API Key by Riot Games, I plan to complete the VALORANT implementation and deploy the service for a one-month testing period.

As mentioned above, if it denied, I will use the valorant-api as a substitute for Riot Games API to provide VALORANT-related search and information features.
