# LIBRARIES


# EXAMPLES, CONFIG.JSON, README.MD, REQUIREMENTS.TXT, RUN.SH


# CLI TOOL
import argparse
# DATAFRAMES TOOL 
import pandas as pd
import json 
import time
import random 
import os
import sys
# FOR DEBUGGING
import logging
from datetime import datetime
# FOR WEB SCRAPPING
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options   
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from sqlalchemy import create_engine


""" 
USAGE MANUAL:

1. pip install -r requirements.txt -> to install dependencies/libraries (with run.sh you run it automatically)
2. We have a CLI that has 1 required argument and 4 optional ones:
    input -> input file (can be CSV or Excel)
    --output -> format of the output file (can be CSV, Excel or JSON), (also from config file you can redirect output to (google sheets, databases and APIs))
    --limit -> it can limit the number of requests done
3. We load the json configuration (if there is not config.json we create a default CONFIG)
4. We set up the logger (it will display information in console)
5. We initialize the driver for the scraping. We have the following options:
    We can set up 'user_agents' from the config.json
    We can set up 'headless' from config.json
    We can set up 'proxy' from config.json
6. We check the input file from CLI. If it is not CSV we exit gracefully. Else we get the urls as a df (if the --limit option was called we limit the number of URLs)
7. We setup a timer to calculate average scraping time and we iterate over all the URLs (if not in config.json is 3 by default) in order to get the data. In each of them:
    We search their URL
    We wait for the page to display at least one of the elements we are searching for. If not we return the URL to a separate list. We will retry until the maximum is reached
    In the config.json we have to setup a 'fields' dictionary to fill the data with that info: 
        the keys in 'fields' will be the keys of the output data and the values in 'fields' will be the CSS classes, ids, etc. to scrape from the web in order to get their values for the output
8. We pass the results to a DataFrame and we create the outfile to pass the data frame to the type we specified in --output
9. Pass the skipped / failed URLs to a CSV file and display the results

"""




# Config
configFile = os.path.join(os.getcwd(), "config.json")
if not os.path.exists(configFile) or not os.path.isfile(configFile): # set default CONFIG
    CONFIG = {
        "fields": {
            "title": "title",
            "price": ".a-price-whole",
            "reviews": "#acrCustomerReviewText"
        },
        "headless": True,
        "proxy": None,
    }
else:
    with open(configFile, "r") as f:
        CONFIG = json.load(f)    
    
    
# Logging setup
logger = logging.getLogger("Weblogger")
level = getattr(logging, CONFIG.get("log_level", "INFO").upper(), logging.INFO)
logger.setLevel(logging.INFO)


consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.INFO)
consoleHandler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

logger.addHandler(consoleHandler)

# Selenium Setup
def init_driver():
    try:
        chrome_options = Options() # Customize the Chrome browser
    
        user_agents = CONFIG.get("user_agents", None)
        if user_agents:
            chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        head = CONFIG.get("headless", None)
        if head and CONFIG["headless"]:
            chrome_options.add_argument("--headless=new") # (no visible browser window)
        chrome_options.add_argument("--disable-gpu") # Disable GPU hardware acceleration
        chrome_options.add_argument("--no-sandbox") # disable Chrome's sandbox security model
        proxy = CONFIG.get("proxy", None)
        if proxy and CONFIG["proxy"]:
            chrome_options.add_argument(f"--proxy-server={CONFIG['proxy']}") # Avoid rate-limits / IP bans
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options) # automatically downloads the correct ChromeDriver for the installed Chrome version and applies all custom settings
        logger.debug("---------- CHROME OPTIONS: --------------")
        for arg in chrome_options.arguments:
            logger.debug(f"\n{arg}")
        return driver 
    except Exception as e:
        logger.error(f"Unable to initialize driver: {e}")
        return None



def scrape_page(driver, url, skipped):
    try:
        
        # Search the url and get the page info to a soup
        driver.get(url)
        
        # Wait for at least one field in CONFIG to load
        first_selector = list(CONFIG["fields"].values())[0]
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, first_selector))
        )
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # We get the element by CSS selector and we get its text and store it in our data dict
        data = {}
        for field, selector in CONFIG["fields"].items():
            element = soup.select_one(selector)
            data[field] = element.get_text(strip=True) if element else None 
        return data
    except Exception as e:
        skipped.append({"url": url, "reason": str(e)})
        raise Exception(e) 


def scrape_with_retries(driver, url, skipped, captcha, retries):
    for attempt in range(1, retries + 1):
        try:
            return scrape_page(driver, url, skipped, captcha)
        except Exception as e:
            logger.warning(f"Retry {attempt} failed for {url}: {e}")
            if attempt == retries:
                return None 

                   
            

def main(input, output, limit):
    # 1. WE INIT THE DRIVER
    driver = init_driver()
    if not driver:
        sys.exit(1)
    
    try:
        # 2. LOAD URLs
        if not os.path.exists(os.path.join(os.getcwd(), input)) or not os.path.isfile(os.path.join(os.getcwd(), input)):
            logger.error(f"Invalid input file: {input} -> does not exist")
            driver.quit()
            sys.exit(1)
        if input.endswith(".csv"):
            urls = pd.read_csv(os.path.join(os.getcwd(), input))["url"].dropna().tolist() # gets all the input in a list and drops the one with empty urls
        else:
            logger.error("Unsupported input format. Please use CSV or Excel with the 'url' column.")
            driver.quit()
            sys.exit(1)
            
        if limit:
            urls = urls[:limit]
        for url in urls:
            logger.debug(f"\n{url}")
        
        # 3. SCRAPE EACH OF THESE URLS AND SAVE THEIR DATA
        results = []
        skipped = []
        
        retries = CONFIG.get("retries", 3)
        logger.debug(f"Retries: {retries}")
        startTime = time.time()
        for url in urls:
            logger.info(f"Scrapping: {url}")
            data = scrape_with_retries(driver, url, skipped, retries)
            if data:
                data["url"] = url 
                results.append(data)
            else:
                continue
        endTime = time.time()
    finally:
        driver.quit()
        
    average_time = (endTime - startTime) / len(urls) if urls else 0
    logger.debug("-------- SCRAPING RESULTS ----------")
    for r in results:
        logger.debug(f"Results: {r}")
    for s in skipped:
        logger.debug(f"Skipped: {s}")
    logger.debug(f"\nStart time: {startTime}\nEnd time: {endTime}")
    logger.debug(f"\nAverage time: {average_time}")
        
    # 4. NOW WE SAVE THE OUTPUT
    df = pd.DataFrame(results)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outfile = f"output_{timestamp}.{output}"
    
    if output == "csv":
        df.to_csv(outfile, index=False)
    elif output == "excel":
        df.to_excel(outfile.replace("excel", "xlsx"), index=False)
    else:
        logger.error("Unsupported output format. Please use csv, excel or json.")
        sys.exit(1)
        
    logger.info(f"Scraping complete. Saved to {outfile}")
    
    # 5. Skipped urls to skipped.txt
    if skipped:
        pd.DataFrame(skipped).to_csv("skipped_report.csv", index=False)
        logger.warning(f"Skipped {len(skipped)} URLs. See skipped_report.csv")
    
    logger.info(f"\n--- SCRAPING REPORT ---\nTotal URLs: {len(urls)}\nURLs scraped: {len(results)}\nURLs skipped: {len(skipped)}\nAverage scrape time per URL: {average_time:.2f} seconds")
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract product prices, reviews, or leads into ready-to-use spreadsheets")
    parser.add_argument("input", help="Input file (CSV with 'url' column)")
    parser.add_argument("--output", default="csv", choices=["csv", "excel"], help="Output format")
    parser.add_argument("--limit", default=None, type=int, help="Scrape only N URLs")
    args = parser.parse_args()
    logger.debug(f"\nINPUT: {args.input}\nOUTPUT: {args.output}\nHEADLESS: {args.headless}\nLIMIT: {args.limit}\nCAPTCHA: {args.captcha}\n")
    logger.debug("--------- CONFIG ITEMS: -----------")
    for key, value in CONFIG.items():
        logger.debug(f"\n{key}: {value}")
    main(args.input, args.output, args.limit)


