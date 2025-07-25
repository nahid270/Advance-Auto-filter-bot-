import asyncio
from pyrogram import Client

async def main():
    api_id = int(input("Enter your API ID: "))
    api_hash = input("Enter your API HASH: ")
    
    async with Client(":memory:", api_id=api_id, api_hash=api_hash) as app:
        session_str = await app.export_session_string()
        print("\n✅ আপনার সেশন স্ট্রিং নিচে দেওয়া হলো। এটি কপি করে .env ফাইলে পেস্ট করুন।\n")
        print(session_str)
        print("\n⚠️ এই স্ট্রিংটি কারো সাথে শেয়ার করবেন না।")

if __name__ == "__main__":
    asyncio.run(main())
