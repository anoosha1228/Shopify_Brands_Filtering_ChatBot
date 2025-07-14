# 🧠 Shopify Brand Filtering Chatbot (Rasa + Apify + MongoDB)

This project is a chatbot developed using **Rasa** in a **virtual environment**. The chatbot helps users find products from Shopify-based brand websites by scraping and returning real-time product data.

---

## 🚀 Features

- Trained on user **intents** with brand names as **entities**
- Maps user queries to **relevant responses**
- Fetches **product data** dynamically from **Shopify-based websites**
- Integrates with **Apify** for web scraping
- Stores product data in **MongoDB**
- Supports product-specific queries

---

## 🧩 Project Workflow

1. **Intent & Entity Creation**
   - Defined multiple **intents** along with example user utterances.
   - Added **brand name** as an entity.
   - Only brands with **Shopify-built websites** were included.

2. **Response Definition**
   - Added appropriate **responses** for each intent in `domain.yml`.

3. **Rule and Story Mapping**
   - Mapped intents to responses using **rules** and **stories** to guide dialogue flow.

4. **Custom Actions**
   - When a **brand entity** is detected:
     - The brand's **sitemap** is searched.
     - The sitemap URL is passed to the **Apify Shopify Scraper**.
     - The scraper collects all products of the brand.
     - Data is stored in a **MongoDB** collection.
   - If the user query also includes a **product entity**:
     - The stored data is **filtered** based on the user’s request.

---

## 🧰 Tech Stack

- **Rasa**
- **Python (Custom Actions)**
- **MongoDB**
- **Apify Shopify Scraper**
- **Virtual Environment** (`venv` or `virtualenv`)

---

## 🛠️ Scrapper Source

- **Apify Shopify Scraper** (https://apify.com/pocesar/shopify-scraper)

---

## 💬 Sample Queries
Try the following queries when interacting with the chatbot:

🔁 Fecthing Brand Data
"User: Show me products from Outfitters"
"Bot: Here are the products available from AllBirds..."

📩 Filtering Data
"User: Do they have any shoes?"
"Bot: Yes, these are the shoes listed on OUtfitters... (along with results in table format)"

---

## 📁 Project Structure

```
Pizza_Ordering_Chatbot/
├── actions/
│   └── actions.py            # Custom scraping & filtering logic
├── data/
│   ├── nlu.yml               # Intents, examples, and entities
│   ├── rules.yml             # Rules mapping
│   └── stories.yml           # Training stories
├── domain.yml                # Responses, slots, entities
├── config.yml                # Rasa pipeline configuration
├── endpoints.yml             # Action server and MongoDB configs
├── README.md                 # Project documentation
└── requirements.txt          # Python dependencies
```

---

## 📌 Notes

✅ Only Shopify-based brand websites are supported.

✅ Apify account and token may be required for production use.

✅ MongoDB is used for temporary product data storage per query.

---

## 🛠️ Setup Instructions

Clone the repo
git clone <repo-url>
cd chatbot_project

Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

Install dependencies
pip install -r requirements.txt

Train the model
rasa train

Start the action server (for custom scraping logic)
rasa run actions

Start the chatbot
rasa shell

---
