import requests
from pymongo import MongoClient, DESCENDING
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
import pandas as pd
from apify_client import ApifyClient
from typing import Any, Text, Dict, List
from rasa_sdk.events import UserUtteranceReverted, ActionExecuted, SessionStarted, SlotSet, Restarted, AllSlotsReset
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

# class ActionRestart(Action):

#     def name(self) -> Text:
#         return "action_restart"

#     async def run(
#         self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]
#     ) -> List[Dict[Text, Any]]:

#         # Retain specific slot values
#         brand_name = tracker.get_slot("brand_name")

#         # Reset the conversation
#         return [Restarted(), SlotSet("brand_name", brand_name)]

class ActionRestart(Action):

    def name(self) -> Text:
        return "action_restart"

    async def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:

        # Define the events to reset the conversation
        events = [
            # Revert back to the user's last message
            UserUtteranceReverted(),
            # Clear all slots
            AllSlotsReset(),
            # This is important to start a new conversation
            SessionStarted(),
            # Mark the restart action as completed
            ActionExecuted("action_restart")
        ]

        return events

class ActionFetchBrandCollectionData(Action):
    def name(self) -> str:
        return "action_fetch_brand_collection"

    async def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> list:
        
        brand_name = tracker.get_slot("brand_name")
        print(brand_name)
        
        collection_name = tracker.get_slot("collection_name")
        print(collection_name)

        product_name = tracker.get_slot("product_name")
        article_name = tracker.get_slot("article_name")
        size = tracker.get_slot("size")

        if product_name or article_name or size:
            return [AllSlotsReset(), SlotSet("brand_name", brand_name), SlotSet("collection_name", collection_name)]

        client = MongoClient("mongodb://localhost:27017/")
        db = client["ecommerce_db"]
        db_collection = db["data"]
        url_collection = db["urls"]
        
        if brand_name:
            brand_data = url_collection.find_one({"brand_name": brand_name.lower()})
            print(brand_data)

            if brand_data:
                brand_url = brand_data["url"]
                print(brand_url)
            else:
                dispatcher.utter_message(text=f'{brand_name} not found in database')
                return []   
        else:
            dispatcher.utter_message(text=f'Brand name mention is not saved in slot. Kindly rephrase what you said.')
            return [UserUtteranceReverted()]
        
        def fetch_sitemap(url):
            sitemap_url = url.rstrip('/') + '/sitemap_collections_1.xml'
            response = requests.get(sitemap_url)
            if response.status_code == 200:
                return response.text
            else:
                return "Sitemap not found"
        
        def parse_sitemap(sitemap_url):
            xml_content = fetch_sitemap(sitemap_url)
            soup = BeautifulSoup(xml_content, 'xml')
            url_tags = soup.find_all('url')
            
            urls = [tag.find('loc').text for tag in url_tags]
            return urls
        
        sitemap = parse_sitemap(brand_url)

        if collection_name:
            keyword = collection_name.lower()
            keyword = keyword.replace(' ', '-')
            keyword_pattern = re.compile(rf'/{keyword}/?$')

            filtered_url = "".join([url for url in sitemap if keyword_pattern.search(url)])
            print (filtered_url)

            if filtered_url:
                # Initialize the ApifyClient with your API token
                client = ApifyClient("apify_api_token")

                # Prepare the Actor input
                run_input = {
                    "startUrls": [{ "url": filtered_url }],
                    "maxRequestsPerCrawl": 15,
                    "proxyConfig": { "useApifyProxy": True },
                    "checkForBanner": True,
                    "extendOutputFunction": """async ({ data, item, product, images, fns, name, request, variants, context, customData, input, Apify }) => {
                return item;
                }""",
                    "extendScraperFunction": """async ({ fns, customData, Apify, label }) => {
                
                }""",
                    "customData": {},
                    "fetchHtml": False,
                    "maxConcurrency": 10,
                    "maxRequestRetries": 3,
                    "debugLog": False,
                }

                # Run the Actor and wait for it to finish
                run = client.actor("kSD0f8dO9UeZke2iY").call(run_input=run_input)

                # Initialize the dataset client
                dataset_client = client.dataset(run["defaultDatasetId"])

                # List items from the Actor's dataset
                dataset_items = dataset_client.list_items().items

                df = pd.DataFrame(dataset_items)

                # Select specific columns
                selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                df = df[selected_columns]

                # Print the filtered DataFrame
                print(df)
                
                filtered_data = df.to_dict('records')

                now = datetime.now()
                date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                document = {
                    "brand_name": brand_name.lower(),
                    "collection": filtered_data,
                    "created_date": date_time
                    }

                db_collection.insert_one(document)

                message = f"Here is the detailed information for the product ({collection_name}) you requested:\nFor further details click on the link of specific product\n"

                if filtered_data:
                    # Determine the maximum width for each column, including the header
                    max_widths = {header: len(header) for header in selected_columns}
                    for item in filtered_data:
                        for key, value in item.items():
                            max_widths[key] = max(max_widths[key], len(str(value)))

                    # Create the table header row
                    header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                    separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                    message += f"\n{header_row}\n{separator_row}\n"
                    
                    # Add each item as a row in the table
                    for item in filtered_data:
                        row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                        message += f"{row}\n"
                else:
                    message = "No products found matching your criteria."

                dispatcher.utter_message(text=message)
                return[SlotSet("collection_info", dataset_items)]

            else:
                dispatcher.utter_message(text=f'{collection_name} not found on {brand_name} site.') 
                return[]

        else:
            dispatcher.utter_message(text=f'Collection mention is not saved in slot. Kindly rephrase what you said.')   
            return[UserUtteranceReverted()]

class ActionFetchProductData(Action):
    def name(self) -> str:
        return "action_fetch_product_name"

    async def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> list:

        brand_name = tracker.get_slot("brand_name")
        print(brand_name)
        
        product_name = tracker.get_slot("product_name")
        print(product_name)
        
        collection_info = tracker.get_slot("collection_info")
        article_info = tracker.get_slot("article_info")
        size_info = tracker.get_slot("size_info")

        client = MongoClient("mongodb://localhost:27017/")
        db = client["ecommerce_db"]
        db_collection = db["data"]
        
        if product_name:
            current_time = datetime.utcnow()
            time_window = timedelta(minutes=1)
            check = 0
            for event in reversed(tracker.events):
                if event.get("event") == "slot":
                    print(event)
                    event_time = datetime.utcfromtimestamp(event.get("timestamp"))
                    if current_time - event_time <= time_window:
                        print("hello2")
                        latest_slot = event.get("name")
                        latest_slot_value = event.get("value")
                        if latest_slot == "collection_info":
                            print("hello3")
                            check = 1
                            break

            print(check)
            if check == 1:
                data = db_collection.find_one({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])

                if data:
                    key_name = list(data.keys())[2]
                else:
                    dispatcher.utter_message(f"No document found for brand_name: {brand_name}")

                if key_name == "collection":
                    key_value = data[key_name]
                    df = pd.DataFrame(key_value)

                    # Filter the DataFrame by product type
                    product_name_filter = product_name 
                    filtered_df = df[df['product_type'].str.contains(product_name_filter, case=False, na=False)]

                    # # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']   # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "product": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the detailed information for the product ({product_name}) you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("product_info", filtered_data)]

                elif key_name == "article":
                    key_value = data[key_name]
                    df = pd.DataFrame(key_value)

                    # Filter the DataFrame by product type
                    product_name_filter = product_name 
                    filtered_df = df[df['product_type'].str.contains(product_name_filter, case=False, na=False)]

                    # # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']   # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "product": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the detailed information for the product ({product_name}) you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("product_info", filtered_data)]

                elif key_name == "size":
                    key_value = data[key_name]
                    df = pd.DataFrame(key_value)

                    # Filter the DataFrame by product type
                    product_name_filter = product_name 
                    filtered_df = df[df['product_type'].str.contains(product_name_filter, case=False, na=False)]

                    # # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']   # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "product": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the detailed information for the product ({product_name}) you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("product_info", filtered_data)]
            else:
                brand_name = tracker.get_slot("brand_name")
                print(brand_name)
                
                product_name = tracker.get_slot("product_name")
                print(product_name)

                collection_name = tracker.get_slot("collection_name")
                article_name = tracker.get_slot("article_name")
                size = tracker.get_slot("size")

                if collection_name or article_name or size:
                    return [AllSlotsReset(), Restarted(), SlotSet("brand_name", brand_name), SlotSet("product_name", product_name)]

                client = MongoClient("mongodb://localhost:27017/")
                db = client["ecommerce_db"]
                db_collection = db["data"]
                url_collection = db["urls"]
                
                if brand_name:
                    brand_data = url_collection.find_one({"brand_name": brand_name.lower()})
                    print(brand_data)

                    if brand_data:
                        brand_url = brand_data["url"]
                        print(brand_url)
                    else:
                        dispatcher.utter_message(text=f'{brand_name} not found in database')
                        return []   
                else:
                    dispatcher.utter_message(text=f'Brand name mention is not saved in slot. Kindly rephrase what you said.')
                    return [UserUtteranceReverted()]
                
                def fetch_sitemap(url):
                    sitemap_url = url.rstrip('/') + '/sitemap_collections_1.xml'
                    response = requests.get(sitemap_url)
                    if response.status_code == 200:
                        return response.text
                    else:
                        return "Sitemap not found"
                
                def parse_sitemap(sitemap_url):
                    xml_content = fetch_sitemap(sitemap_url)
                    soup = BeautifulSoup(xml_content, 'xml')
                    url_tags = soup.find_all('url')
                    
                    urls = [tag.find('loc').text for tag in url_tags]
                    return urls
                
                sitemap = parse_sitemap(brand_url)

                if product_name:
                    keyword = product_name.lower()
                    keyword = keyword.replace(' ', '-')
                    keyword_pattern = re.compile(rf'/{keyword}/?$')

                    filtered_url = "".join([url for url in sitemap if keyword_pattern.search(url)])
                    print (filtered_url)

                    if filtered_url:
                        # Initialize the ApifyClient with your API token
                        client = ApifyClient("apify_api_token")

                        # Prepare the Actor input
                        run_input = {
                            "startUrls": [{ "url": filtered_url }],
                            "maxRequestsPerCrawl": 30,
                            "proxyConfig": { "useApifyProxy": True },
                            "checkForBanner": True,
                            "extendOutputFunction": """async ({ data, item, product, images, fns, name, request, variants, context, customData, input, Apify }) => {
                        return item;
                        }""",
                            "extendScraperFunction": """async ({ fns, customData, Apify, label }) => {
                        
                        }""",
                            "customData": {},
                            "fetchHtml": False,
                            "maxConcurrency": 10,
                            "maxRequestRetries": 3,
                            "debugLog": False,
                        }

                        # Run the Actor and wait for it to finish
                        run = client.actor("kSD0f8dO9UeZke2iY").call(run_input=run_input)

                        # Initialize the dataset client
                        dataset_client = client.dataset(run["defaultDatasetId"])

                        # List items from the Actor's dataset
                        dataset_items = dataset_client.list_items().items

                        df = pd.DataFrame(dataset_items)

                        # Select specific columns
                        selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                        df = df[selected_columns]

                        # Print the filtered DataFrame
                        print(df)
                        
                        filtered_data = df.to_dict('records')

                        now = datetime.now()
                        date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                        document = {
                            "brand_name": brand_name.lower(),
                            "collection": filtered_data,
                            "created_date": date_time
                            }

                        db_collection.insert_one(document)

                        message = f"Here is the detailed information for the product ({product_name}) you requested:\nFor further details click on the link of specific product\n"

                        if filtered_data:
                            # Determine the maximum width for each column, including the header
                            max_widths = {header: len(header) for header in selected_columns}
                            for item in filtered_data:
                                for key, value in item.items():
                                    max_widths[key] = max(max_widths[key], len(str(value)))

                            # Create the table header row
                            header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                            separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                            message += f"\n{header_row}\n{separator_row}\n"
                            
                            # Add each item as a row in the table
                            for item in filtered_data:
                                row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                                message += f"{row}\n"
                        else:
                            message = "No products found matching your criteria."

                        dispatcher.utter_message(text=message)
                        return[SlotSet("product_info", dataset_items)]

                    else:
                        dispatcher.utter_message(text=f'{product_name} not found on {brand_name} site.') 
                        return[]

                else:
                    dispatcher.utter_message(text=f'Product mention is not saved in slot. Kindly rephrase what you said.')   
                    return[UserUtteranceReverted()]  

        else:
            dispatcher.utter_message(text=f'Product mentioned is not saved in slot. Kindly rephrase what you said.')
            return [UserUtteranceReverted()]


class ActionFetchArticleData(Action):
    def name(self) -> str:
        return "action_fetch_article_name"

    async def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> list:
        brand_name = tracker.get_slot("brand_name")
        print(brand_name)

        article_name = tracker.get_slot("article_name")
        print(article_name)
        
        product_info = tracker.get_slot("product_info")
        collection_info = tracker.get_slot("collection_info")
        size_info = tracker.get_slot("size_info")
        print(f'product_info: {product_info}')
        print(f'collection_info: {collection_info}')
        print(f'size_info: {size_info}')

        client = MongoClient("mongodb://localhost:27017/")
        db = client["ecommerce_db"]
        db_collection = db["data"]
        
        if article_name:
            data = db_collection.find_one({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])

            if data:
                key_name = list(data.keys())[2]
            else:
                dispatcher.utter_message(f"No document found for brand_name: {brand_name}")

            # Convert tracker.events into a list
            # events_list = list(tracker.events)
            # second_last_event = events_list[-2]

            # if second_last_event.get("event") == "slot":
            #     latest_slot = second_last_event.get("name")
            #     latest_slot_value = second_last_event.get("value")
            # else:
            #     print("no slot info found")

            # for event in reversed(tracker.events):
            #     if event.get("event") == "slot":
            #         latest_slot = event.get("name")
            #         latest_slot_value = event.get("value")
            #         break

            # count_slot_events = 0
            # for event in reversed(tracker.events):
            #     if event.get("event") == "slot":
            #         count_slot_events += 1
            #         if count_slot_events == 2:
            #             latest_slot = event.get("name")
            #             latest_slot_value = event.get("value")
            #             break

            if key_name == "collection":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)

                # Filter the DataFrame by product type
                article_name_filter = article_name 

                filtered_df = df[df['title'].str.contains(article_name_filter, case=False, na=False)]

                # Select specific columns
                selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                filtered_df = filtered_df[selected_columns]

                # Print the filtered DataFrame
                print(filtered_df)
                
                filtered_data = filtered_df.to_dict('records')

                now = datetime.now()
                date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                
                # Print the retrieved items
                document = {
                    "brand_name": brand_name,
                    "article": filtered_data,
                    "created_date": date_time
                }

                db_collection.insert_one(document)

                message = f"Here is the detailed information for the product ({article_name}) you requested:\nFor further details click on the link of specific product\n"

                if filtered_data:
                    # Determine the maximum width for each column, including the header
                    max_widths = {header: len(header) for header in selected_columns}
                    for item in filtered_data:
                        for key, value in item.items():
                            max_widths[key] = max(max_widths[key], len(str(value)))

                    # Create the table header row
                    header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                    separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                    message += f"\n{header_row}\n{separator_row}\n"
                    
                    # Add each item as a row in the table
                    for item in filtered_data:
                        row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                        message += f"{row}\n"

                else:
                    message = "No products found matching your criteria."

                dispatcher.utter_message(text=message)
                return[SlotSet("article_info", filtered_data)]

            elif key_name == "product":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)
                if not df.empty:

                    # Filter the DataFrame by product type
                    article_name_filter = article_name 

                    filtered_df = df[df['title'].str.contains(article_name_filter, case=False, na=False)]

                    # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                    
                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "article": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the detailed information for the product ({article_name}) you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("article_info", filtered_data)]
                
                else:
                    data = db_collection.find({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])
                    
                    for record in data:
                        key_name = list(record.keys())[2]
                        if key_name == "collection":
                            key_value = record[key_name]
                            break

                    print(check)
                    if key_name == "collection":
                        df = pd.DataFrame(key_value)
                        # Filter the DataFrame by product type
                        article_name_filter = article_name 

                        filtered_df = df[df['title'].str.contains(article_name_filter, case=False, na=False)]

                        # Select specific columns
                        selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                        filtered_df = filtered_df[selected_columns]

                        # Print the filtered DataFrame
                        print(filtered_df)
                        
                        filtered_data = filtered_df.to_dict('records')

                        now = datetime.now()
                        date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                        
                        # Print the retrieved items
                        document = {
                            "brand_name": brand_name,
                            "article": filtered_data,
                            "created_date": date_time
                        }

                        db_collection.insert_one(document)

                        message = f"Here is the detailed information for the product ({article_name}) you requested:\nFor further details click on the link of specific product\n"

                        if filtered_data:
                            # Determine the maximum width for each column, including the header
                            max_widths = {header: len(header) for header in selected_columns}
                            for item in filtered_data:
                                for key, value in item.items():
                                    max_widths[key] = max(max_widths[key], len(str(value)))

                            # Create the table header row
                            header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                            separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                            message += f"\n{header_row}\n{separator_row}\n"
                            
                            # Add each item as a row in the table
                            for item in filtered_data:
                                row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                                message += f"{row}\n"

                        else:
                            message = "No products found matching your criteria."

                    else:
                        message = "No products found. Search for collectiona and then filter"

                dispatcher.utter_message(text=message)
                return[SlotSet("article_info", filtered_data)]

            elif key_name == "size":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)

                if not df.empty:

                    # Filter the DataFrame by product type
                    article_name_filter = article_name 

                    filtered_df = df[df['title'].str.contains(article_name_filter, case=False, na=False)]

                    # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                    
                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "article": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the detailed information for the product ({article_name}) you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("article_info", filtered_data)]
                else:

                    data = db_collection.find({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])

                    for record in data:
                        key_name = list(record.keys())[2]
                        if key_name == "collection":
                            key_value = record[key_name]
                            break

                    if key_name == "collection":
                        df = pd.DataFrame(key_value)
                        
                        article_name_filter = article_name 

                        filtered_df = df[df['title'].str.contains(article_name_filter, case=False, na=False)]

                        # Select specific columns
                        selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                        filtered_df = filtered_df[selected_columns]

                        # Print the filtered DataFrame
                        print(filtered_df)
                        
                        filtered_data = filtered_df.to_dict('records')

                        now = datetime.now()
                        date_time = now.strftime("%d/%m/%Y %H:%M:%S")
                        
                        # Print the retrieved items
                        document = {
                            "brand_name": brand_name,
                            "article": filtered_data,
                            "created_date": date_time
                        }

                        db_collection.insert_one(document)

                        message = f"Here is the detailed information for the product ({article_name}) you requested:\nFor further details click on the link of specific product\n"

                        if filtered_data:
                            # Determine the maximum width for each column, including the header
                            max_widths = {header: len(header) for header in selected_columns}
                            for item in filtered_data:
                                for key, value in item.items():
                                    max_widths[key] = max(max_widths[key], len(str(value)))

                            # Create the table header row
                            header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                            separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                            message += f"\n{header_row}\n{separator_row}\n"
                            
                            # Add each item as a row in the table
                            for item in filtered_data:
                                row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                                message += f"{row}\n"

                        else:
                            message = "No products found matching your criteria."

                    else:
                        message = "No products found. Search for collectiona and then filter"

                dispatcher.utter_message(text=message)
                return[SlotSet("article_info", filtered_data)]
          
        else:
            dispatcher.utter_message(text=f'Article mentioned is not saved in slot. Kindly rephrase what you said.')
            return [UserUtteranceReverted()]

class ActionFetchSizeData(Action):
    def name(self) -> str:
        return "action_fetch_size"

    async def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> list:
        brand_name = tracker.get_slot("brand_name")
        print(brand_name)

        size = tracker.get_slot("size")
        print(size)
        
        article_info = tracker.get_slot("article_info")
        print(article_info)

        client = MongoClient("mongodb://localhost:27017/")
        db = client["ecommerce_db"]
        db_collection = db["data"]
        
        if size:
            data = db_collection.find_one({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])
            print(data)

            if data:
                key_name = list(data.keys())[2]
            else:
                dispatcher.utter_message(f"No data found for brand_name: {brand_name} yet in our DB. try searching some articles")

            if key_name == "collection":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)

                # Filter the DataFrame by product type
                size_filter = size 

                filtered_df = df[df['size'].str.contains(size_filter, case=False, na=False)]

                # # Select specific columns
                selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                filtered_df = filtered_df[selected_columns]

                # # Print the filtered DataFrame
                print(filtered_df)
                
                filtered_data = filtered_df.to_dict('records')

                now = datetime.now()
                date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                # Print the retrieved items
                document = {
                    "brand_name": brand_name,
                    "size": filtered_data,
                    "created_date": date_time
                }

                db_collection.insert_one(document)

                message = f"Here is the filtered details you requested:\nFor further details click on the link of specific product\n"

                if filtered_data:
                    # Determine the maximum width for each column, including the header
                    max_widths = {header: len(header) for header in selected_columns}
                    for item in filtered_data:
                        for key, value in item.items():
                            max_widths[key] = max(max_widths[key], len(str(value)))

                    # Create the table header row
                    header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                    separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                    message += f"\n{header_row}\n{separator_row}\n"
                    
                    # Add each item as a row in the table
                    for item in filtered_data:
                        row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                        message += f"{row}\n"

                else:
                    message = "No products found matching your criteria."

                dispatcher.utter_message(text=message)
                return[SlotSet("size_info", filtered_data)]

            elif key_name == "product":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)

                if not df.empty:

                    # Filter the DataFrame by product type
                    size_filter = size 

                    filtered_df = df[df['size'].str.contains(size_filter, case=False, na=False)]

                    # # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "size": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the filtered details you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("size_info", filtered_data)]
                
                else:
                    data = db_collection.find({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])

                    for record in data:
                        key_name = list(record.keys())[2]
                        if key_name == "collection":
                            key_value = record[key_name]
                            break

                    if key_name == "collection":
                        df = pd.DataFrame(key_value)
                        # Filter the DataFrame by product type
                        size_filter = size 

                        filtered_df = df[df['size'].str.contains(size_filter, case=False, na=False)]

                        # # Select specific columns
                        selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                        filtered_df = filtered_df[selected_columns]

                        # # Print the filtered DataFrame
                        print(filtered_df)
                        
                        filtered_data = filtered_df.to_dict('records')

                        now = datetime.now()
                        date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                        # Print the retrieved items
                        document = {
                            "brand_name": brand_name,
                            "size": filtered_data,
                            "created_date": date_time
                        }

                        db_collection.insert_one(document)

                        message = f"Here is the filtered details you requested:\nFor further details click on the link of specific product\n"

                        if filtered_data:
                            # Determine the maximum width for each column, including the header
                            max_widths = {header: len(header) for header in selected_columns}
                            for item in filtered_data:
                                for key, value in item.items():
                                    max_widths[key] = max(max_widths[key], len(str(value)))

                            # Create the table header row
                            header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                            separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                            message += f"\n{header_row}\n{separator_row}\n"
                            
                            # Add each item as a row in the table
                            for item in filtered_data:
                                row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                                message += f"{row}\n"

                        else:
                            message = "No products found matching your criteria."
                    else:
                        message = "No products found. Search for collectiona and then filter"

                    dispatcher.utter_message(text=message)
                    return[SlotSet("size_info", filtered_data)]

            elif key_name == "article":
                key_value = data[key_name]
                df = pd.DataFrame(key_value)
                
                if not df.empty:
                    # Filter the DataFrame by product type
                    size_filter = size 

                    filtered_df = df[df['size'].str.contains(size_filter, case=False, na=False)]

                    # # Select specific columns
                    selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                    filtered_df = filtered_df[selected_columns]

                    # # Print the filtered DataFrame
                    print(filtered_df)
                    
                    filtered_data = filtered_df.to_dict('records')

                    now = datetime.now()
                    date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # Print the retrieved items
                    document = {
                        "brand_name": brand_name,
                        "size": filtered_data,
                        "created_date": date_time
                    }

                    db_collection.insert_one(document)

                    message = f"Here is the filtered details you requested:\nFor further details click on the link of specific product\n"

                    if filtered_data:
                        # Determine the maximum width for each column, including the header
                        max_widths = {header: len(header) for header in selected_columns}
                        for item in filtered_data:
                            for key, value in item.items():
                                max_widths[key] = max(max_widths[key], len(str(value)))

                        # Create the table header row
                        header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                        separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                        message += f"\n{header_row}\n{separator_row}\n"
                        
                        # Add each item as a row in the table
                        for item in filtered_data:
                            row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                            message += f"{row}\n"

                    else:
                        message = "No products found matching your criteria."

                    dispatcher.utter_message(text=message)
                    return[SlotSet("size_info", filtered_data)]

                else:
                    data = db_collection.find({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])

                    for record in data:
                        key_name = list(record.keys())[2]
                        if key_name == "collection":
                            key_value = record[key_name]
                            break
                    
                    if key_name == "collection":
                        df = pd.DataFrame(key_value)
                        # Filter the DataFrame by product type
                        size_filter = size 

                        filtered_df = df[df['size'].str.contains(size_filter, case=False, na=False)]

                        # # Select specific columns
                        selected_columns = ['product_type', 'title', 'price', 'size', 'url']  # Adjust to your specific column names
                        filtered_df = filtered_df[selected_columns]

                        # # Print the filtered DataFrame
                        print(filtered_df)
                        
                        filtered_data = filtered_df.to_dict('records')

                        now = datetime.now()
                        date_time = now.strftime("%d/%m/%Y %H:%M:%S")

                        # Print the retrieved items
                        document = {
                            "brand_name": brand_name,
                            "size": filtered_data,
                            "created_date": date_time
                        }

                        db_collection.insert_one(document)

                        message = f"Here is the filtered details you requested:\nFor further details click on the link of specific product\n"

                        if filtered_data:
                            # Determine the maximum width for each column, including the header
                            max_widths = {header: len(header) for header in selected_columns}
                            for item in filtered_data:
                                for key, value in item.items():
                                    max_widths[key] = max(max_widths[key], len(str(value)))

                            # Create the table header row
                            header_row = " | ".join(f"{header:<{max_widths[header]}}" for header in selected_columns)
                            separator_row = "-+-".join('-' * max_widths[header] for header in selected_columns)
                            message += f"\n{header_row}\n{separator_row}\n"
                            
                            # Add each item as a row in the table
                            for item in filtered_data:
                                row = " | ".join(f"{str(item.get(header, '')):<{max_widths[header]}}" for header in selected_columns)
                                message += f"{row}\n"

                        else:
                            message = "No products found matching your criteria."
                    else:
                        message = "No products found. Search for collectiona and then filter"

                    dispatcher.utter_message(text=message)
                    return[SlotSet("size_info", filtered_data)]
                     
            else:
                dispatcher.utter_message("Kindly search data step by step")
  
        else:
            dispatcher.utter_message(text=f'Brand name mention is not saved in slot. Kindly rephrase what you said.')
            return []

class ActionRegister(Action):
    def name(self) -> str:
        return "action_register"

    async def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> list:

        brand_name = tracker.get_slot("brand_name")

        name = tracker.get_slot("name")
        number = tracker.get_slot("number")
        address = tracker.get_slot("address")
        email = tracker.get_slot("email")

        client = MongoClient("mongodb://localhost:27017/")
        db = client["ecommerce_db"]
        db_collection = db["data"]
        cred_collection = db["credentials"]

        data = db_collection.find_one(
            {"brand_name": brand_name}, 
            sort=[('created_date', DESCENDING)]
        )
        print(data)

        authentication = cred_collection.find_one({name: name}, sort=[("created_date", -1)])
        print(authentication)

        now = datetime.now()
        date_time = now.strftime("%d/%m/%Y %H:%M:%S")

        if data:
            if authentication:
                cred_collection.update_one({"$set": {"items": data}})
            # user_info = {
            #     "name": tracker.get_slot("name"),
            #     "number": tracker.get_slot("number"),
            #     "address": tracker.get_slot("address"),
            #     "email": tracker.get_slot("email")
            # }
            else:
                document = {
                    "name": name,
                    "number": number,
                    "address": address,
                    "email": email,
                    "items": data,
                    "created_date": date_time
                }

                length = len(data)

                cred_collection.insert_one(document)

                dispatcher.utter_message(f"Thank you {name} for placing order. Your credentials are: Address: {address}, Phone No. {number} and E-mail: {email}. And the total number of products you have ordered are {length}.")
                return[]

        else: 
            dispatcher.utter_message(f"No data found. Kindly search some product than add those product to cart.")
            return[]
        
# class ActionFetchOneProduct(Action):
#     def name(self) -> str:
#         return "action_fetch_one_product"

#     async def run(self, dispatcher: CollectingDispatcher,
#             tracker: Tracker,
#             domain: dict) -> list:
        
#         brand_name = tracker.get_slot("brand_name")

#         name = tracker.get_slot("name")
#         number = tracker.get_slot("number")
#         address = tracker.get_slot("address")
#         email = tracker.get_slot("email")

#         client = MongoClient("mongodb://localhost:27017/")
#         db = client["ecommerce_db"]
#         db_collection = db["data"]

#         data = db_collection.find_one({"brand_name": brand_name.lower()}, sort=[("created_date", -1)])
#         print(data)

#         if data:
#             key_name = list(data.keys())[2]
#         else:
#             dispatcher.utter_message(f"No data found for brand_name: {brand_name} yet in our DB. try searching some articles")

#         if key_name == "collection":
#             key_value = data[key_name]
#             df = pd.DataFrame(key_value)

#         if not filtered_data or selected_index < 0 or selected_index >= len(filtered_data):
#             dispatcher.utter_message(text="The provided index is out of range. Please try again.")
#             return []

#         selected_product = filtered_data[selected_index]

#         # Create a detailed message for the selected product
#         product_details = "\n".join([f"{key}: {value}" for key, value in selected_product.items()])
#         dispatcher.utter_message(text=f"Here are the details for the selected product:\n{product_details}")

        
         




