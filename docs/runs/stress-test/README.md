# Stress test: 18 unseen goals

Run on 2026-10-17 with planner `claude-sonnet-5-5`, Jev `jev-latest` and text helper `claude-haiku-5-5`, 3 at a time,
unattended (risky steps auto-approved; a question for the operator ends the run). Time zone America/New_York.
Goals were written to resemble what an evaluator might type; nothing in the engine is specific to them.
Raw step logs: the JSON files in this folder. "Success" is the agent's own claim; each answer was then read by hand.

| Goal | Success | Time | Planner cost | First caveat the agent reported |
| --- | --- | --- | --- | --- |
| What are the next 3 upcoming SpaceX launches? Give date, rocket, mission and launch site. | yes | 29 s | $0.08 | Dates for the first two launches are inferred from the weekday shown and today's date. |
| Summarize the top 3 news stories on Wikipedia's Current events page for today. | yes | 13 s | $0.07 |  |
| Find the cheapest one-way flight from New York to London next Friday and give me the airline, times and price. | yes | 51 s | $0.18 | Prices are as shown on Kayak at the time of search and may change. |
| List the top 10 trending Python repositories on GitHub today with the stars they gained today. | yes | 20 s | $0.12 | elder-plinius/V3R1T4S appears under the Python filter, but its page labels it as C. |
| On quotes.toscrape.com, collect every quote tagged "love" across all pages, with its author. | yes | 28 s | $0.15 | Some long quotes are abbreviated in the saved findings. |
| What are the current exchange rates from 1 USD to EUR, GBP and JPY? | yes | 22 s | $0.11 | The page's timestamp reads 'Jan 01, 2026 05:12 UTC', which doesn't match today's date (17 Oct 2026). The rates may not be live. |
| What are the 3 most recent stable versions of React on npm and when was each published? | yes | 16 s | $0.07 | npm shows only relative dates (e.g. '3 days ago'); exact timestamps were not checked. |
| Log in at https://the-internet.herokuapp.com/login with username tomsmith and password SuperSecretPassword! and tell me the message you see after logging in. | yes | 28 s | $0.12 |  |
| What is the address, phone number and today's opening hours of the Apple Store on Fifth Avenue in New York? | yes | 15 s | $0.07 |  |
| Compare the iPhone 17 and the Google Pixel 10 from their official websites: screen size, battery and starting price. | yes | 41 s | $0.25 | Prices are from different regional stores (US for Apple, India for Google) and in different currencies, so they aren't directly comparable. |
| Find the 3 most recent arXiv papers about browser agents and give title, authors and abstract in one sentence each. | yes | 59 s | $0.26 | Selection is based on the arXiv search for the phrase "browser agent", sorted by announcement date. Papers that use different wording may ha |
| On Target.com, find the cheapest 12 oz bag of whole bean coffee and give its name, brand, price and link. | – | – | – | Waited for the operator to solve a bot check (Target). In the UI this shows as a question you can answer by taking over. |
| Find the 3 most recent posts on Anthropic's news page and summarize each in one sentence with links. | yes | 23 s | $0.14 | The midterms and Singapore posts were summarized from the related-content blurbs on the first post, not by opening them. |
| Using Wikipedia, give me a table of the 5 largest countries by area with their area and population. | yes | 35 s | $0.30 |  |
| Find 3 remote senior frontend engineer job postings from this week with company, title and a link to apply. | no | 97 s | $0.79 | Only 1 loosely related posting found this week; fewer than the 3 requested |
| Fill out the web form at https://www.selenium.dev/selenium/web/web-form.html with sample data (text, password, textarea, dropdown, checkbox, radio, date), submit it, and tell me what the confirmation page says. | yes | 39 s | $0.27 | The date field was empty in the submitted URL (my-date=), so my typed date may not have registered. |
| Compare the US monthly price of the cheapest ad-free plan for Netflix, Spotify Premium and YouTube Premium. | yes | 40 s | $0.29 | Prices come from HonestlyRanked's manually maintained records, not live checkout quotes. |
| What are the British Museum's opening hours today and is general admission free? | yes | 14 s | $0.07 | The 10.00 opening time today is assumed from the normal daily hours; the alert only mentions the 13.00 closure. |

16 of 18 report success. The two that do not are honest failures: remote-jobs found only one matching posting this
week and said so instead of padding the list, and Target showed a bot check, so the agent asked the operator for help.
