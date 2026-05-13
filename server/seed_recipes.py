import json
import os
import sqlite3

DB_PATH = "users.db"

def seed_recipes():
    recipes = [
        {
            "title": "Omelette",
            "scenario": "A quick and fluffy breakfast classic to start your morning right.",
            "ingredients": [
                {"name": "Eggs", "quantity": "3", "unit": "pcs"},
                {"name": "Milk", "quantity": "1", "unit": "tbsp"},
                {"name": "Butter", "quantity": "1", "unit": "tsp"},
                {"name": "Salt/Pepper", "quantity": "1", "unit": "pinch"}
            ],
            "steps": [
                "Whisk eggs and milk in a bowl until combined.",
                "Melt butter in a non-stick pan over medium heat.",
                "Pour in egg mixture and let sit for 30 seconds.",
                "Fold the omelette in half and slide onto a plate."
            ],
            "time_context": "Breakfast"
        },
        {
            "title": "Pizza Margheritta",
            "scenario": "A traditional Italian lunch staple with fresh basil and mozzarella.",
            "ingredients": [
                {"name": "Pizza Dough", "quantity": "1", "unit": "ball"},
                {"name": "Tomato Sauce", "quantity": "0.5", "unit": "cup"},
                {"name": "Mozzarella", "quantity": "100", "unit": "g"},
                {"name": "Basil Leaves", "quantity": "5", "unit": "pcs"}
            ],
            "steps": [
                "Preheat oven to 250°C (480°F).",
                "Roll out the dough on a floured surface.",
                "Spread tomato sauce and top with mozzarella.",
                "Bake for 10-12 minutes until crust is golden."
            ],
            "time_context": "Lunch/Dinner"
        },
        {
            "title": "Creamy Pasta",
            "scenario": "A rich and comforting dinner dish perfect for a cozy evening.",
            "ingredients": [
                {"name": "Pasta", "quantity": "200", "unit": "g"},
                {"name": "Heavy Cream", "quantity": "1", "unit": "cup"},
                {"name": "Parmesan", "quantity": "50", "unit": "g"},
                {"name": "Garlic", "quantity": "2", "unit": "cloves"}
            ],
            "steps": [
                "Boil pasta in salted water until al dente.",
                "Sauté garlic in a pan, then add cream and parmesan.",
                "Toss the pasta into the sauce until coated.",
                "Serve immediately with extra black pepper."
            ],
            "time_context": "Lunch/Dinner"
        },
        {
            "title": "Chocolate Cake",
            "scenario": "The ultimate dessert reward after a successful meal.",
            "ingredients": [
                {"name": "Flour", "quantity": "1.5", "unit": "cups"},
                {"name": "Cocoa Powder", "quantity": "0.5", "unit": "cup"},
                {"name": "Sugar", "quantity": "1", "unit": "cup"},
                {"name": "Eggs", "quantity": "2", "unit": "pcs"}
            ],
            "steps": [
                "Mix dry ingredients in a large bowl.",
                "Whisk in eggs, oil, and water until smooth.",
                "Pour into a greased pan and bake at 180°C for 30 mins.",
                "Let cool before frosting with chocolate ganache."
            ],
            "time_context": "Dessert"
        }
    ]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Clear existing recipes to avoid duplicates during testing
    cursor.execute("DELETE FROM RECIPE")
    
    for r in recipes:
        cursor.execute("""
            INSERT INTO RECIPE (title, scenario, steps_json, ingredients_json)
            VALUES (?, ?, ?, ?)
        """, (
            r["title"],
            r["scenario"],
            json.dumps(r["steps"]),
            json.dumps(r["ingredients"])
        ))
    
    conn.commit()
    conn.close()
    print(f"Successfully seeded {len(recipes)} recipes into {DB_PATH}")

if __name__ == "__main__":
    seed_recipes()
