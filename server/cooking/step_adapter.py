"""
step_adapter.py — Profession-aware step expansion for the Kitchen Assistant.

Usage:
    from cooking.step_adapter import adapt_steps

    adapted = adapt_steps(recipe["steps_json"], recipe_id, skill_level)

Rules:
  • skill_level == "Chef"  (or anything other than "home cook") → original steps unchanged.
  • skill_level == "Home Cook" (case-insensitive) → expanded, beginner-friendly steps.

The expanded steps are intentionally written to be a richer, more detailed version
of the chef steps, NOT replacements.  They contain timings, visual cues, temperatures,
and simple explanations so a home cook knows exactly what to do and why.

The emotion-based adaptive support in cooking_session.py works ADDITIVELY on top of
whichever step text is selected here — so a Home Cook who shows distress will get
the expanded text PLUS the emotional focus tip appended at the end.
"""

# ─────────────────────────────────────────────────────────────────────────────
#  recipe_id → list[expanded step str]   (0-indexed, same length as DB steps)
# ─────────────────────────────────────────────────────────────────────────────
HOME_COOK_STEPS: dict[int, list[str]] = {

    # ── Recipe 1: Omelette ───────────────────────────────────────────────────
    1: [
        (
            "Crack 3 eggs one at a time into a bowl — tap gently on the rim and pull the shell apart "
            "over the bowl. Remove any shell fragments with a wet finger (they stick to it). "
            "Add 1 tablespoon of milk. Whisk briskly with a fork for about 30 seconds until the "
            "yolk and white fully blend and the mixture looks slightly frothy."
        ),
        (
            "Place a non-stick frying pan on a medium burner (about 5 out of 10 on your stove dial). "
            "Add 1 teaspoon of butter. Wait roughly 30 seconds until the butter fully melts and the "
            "bubbling slows down — this tells you the pan is ready. Tilt the pan in a circle so the "
            "melted butter coats the entire base."
        ),
        (
            "Pour your whisked egg mixture into the pan in one smooth motion. Let it sit completely "
            "untouched for 30 full seconds so the bottom layer can set. Once you see the edges "
            "starting to look opaque (no longer clear/runny), use a rubber spatula to gently push the "
            "set edges inward while tilting the pan so the uncooked liquid egg flows outward to the "
            "edges. Repeat this 2-3 times until most of the surface looks just set — slightly shiny on "
            "top is perfectly fine."
        ),
        (
            "When the top of the omelette looks just barely set (a small amount of shine is okay — it "
            "will finish cooking from the residual heat), use your spatula to fold one half of the "
            "omelette over the other to form a half-moon shape. Slide it gently onto your plate "
            "without flipping. Season with a pinch of salt and black pepper. Serve immediately — "
            "omelettes cool quickly!"
        ),
    ],

    # ── Recipe 2: Pizza Margherita ───────────────────────────────────────────
    2: [
        (
            "Turn your oven to its highest temperature — ideally 250 °C (480 °F) or as high as it goes. "
            "Place your oven rack in the middle or upper-middle position. Allow the oven to fully "
            "preheat for at least 15 minutes so the heat is even throughout. If you have a baking stone "
            "or heavy baking tray, put it in the oven now so it heats up too — this helps the crust crisp."
        ),
        (
            "Lightly dust a clean, flat surface (your counter or a large chopping board) with flour. "
            "Place your dough ball in the centre and use the heel of your hand to press it out from "
            "the centre outward. Rotate the dough a quarter turn after each push. Don't use a rolling "
            "pin — your hands give you better control and keep air bubbles in the dough. Aim for a "
            "round roughly 25–30 cm (10–12 inches) wide with slightly thicker edges for the crust."
        ),
        (
            "Spoon about ½ cup (125 ml) of tomato sauce onto the centre of your dough. Use the back "
            "of the spoon in a circular motion to spread it outward, leaving about 2 cm (1 inch) of "
            "bare dough all around the edge — this becomes your crust. Tear or slice 100 g of "
            "mozzarella and scatter evenly over the sauce. Don't pile it too thick or it won't melt "
            "evenly. Leave gaps — the tomato showing through is part of the classic look."
        ),
        (
            "Carefully slide your pizza onto the hot baking stone or tray in the oven. Bake for 10–12 "
            "minutes. Start checking at 10 minutes — you're looking for a golden-brown crust, bubbling "
            "cheese with a few brown spots, and sauce that looks dry (not wet). Remove from the oven "
            "and immediately scatter fresh basil leaves on top. Let rest 2 minutes before slicing — "
            "the cheese needs to set slightly or it will all slide off when you cut it."
        ),
    ],

    # ── Recipe 3: Creamy Pasta ───────────────────────────────────────────────
    3: [
        (
            "Fill a large pot with water — about 3–4 litres for 200 g of pasta. Add 1–2 teaspoons "
            "of salt (the water should taste lightly salty, like the sea). Bring to a rolling boil "
            "over high heat — this can take 8–10 minutes. Once boiling, add 200 g of pasta. Stir "
            "immediately and stir again every minute or so to prevent sticking. Cook for the time "
            "on the packet minus 1 minute for 'al dente' — firm to the bite. Before draining, "
            "scoop out ½ cup of the starchy pasta water and set aside. It's liquid gold for the sauce!"
        ),
        (
            "While the pasta cooks, peel and finely chop 2 garlic cloves — the smaller the pieces, "
            "the more flavour releases. Place a wide pan on medium-low heat (4 out of 10) and add a "
            "small drizzle of olive oil or a knob of butter. Add the garlic and stir constantly for "
            "60–90 seconds until it smells fragrant and turns pale gold — do NOT let it turn brown "
            "or it will taste bitter. Pour in 1 cup (250 ml) of heavy cream. Stir gently and let it "
            "come to a gentle simmer (small bubbles around the edges). Add 50 g of grated parmesan "
            "and stir until fully melted into a smooth, creamy sauce. Season with salt and pepper."
        ),
        (
            "Drain your pasta through a colander but do NOT rinse it — the surface starch is what "
            "helps the sauce cling. Tip the drained pasta directly into the pan with your cream "
            "sauce. Toss everything together using kitchen tongs or two large spoons. If the sauce "
            "looks too thick or clumpy, add a splash of your reserved pasta water (a tablespoon at "
            "a time) and toss again — the starch in the water helps create a silky, glossy coating."
        ),
        (
            "Serve immediately onto warmed plates — pasta cools and stiffens quickly. Finish with a "
            "generous crack of black pepper and extra grated parmesan on top. Optional: a small drizzle "
            "of good olive oil or a few fresh basil leaves adds a restaurant-quality finish. Eat right "
            "away while it's at its creamiest!"
        ),
    ],

    # ── Recipe 4: Chocolate Cake ─────────────────────────────────────────────
    4: [
        (
            "In a large mixing bowl, combine your dry ingredients: 1½ cups (190 g) plain flour, "
            "½ cup (50 g) unsweetened cocoa powder, 1 cup (200 g) sugar, 1 teaspoon baking soda, "
            "and a pinch of salt. Use a whisk or fork to stir them together — this also aerates the "
            "mixture and prevents lumps. Whisking dry ingredients first ensures your cocoa and "
            "leavening are evenly distributed so the cake rises uniformly."
        ),
        (
            "In a separate jug or bowl, beat 2 eggs lightly with a fork. Add ½ cup (120 ml) "
            "vegetable oil and 1 cup (240 ml) warm water. Stir to combine. Pour the wet ingredients "
            "into the bowl of dry ingredients all at once. Use a large spoon or spatula to fold them "
            "together using big, gentle circular strokes — mix until just combined and no dry flour "
            "pockets remain. Do NOT over-mix: a few small lumps are fine; over-mixing makes the "
            "cake tough."
        ),
        (
            "Grease your cake tin (20–22 cm round) with butter and dust lightly with flour, or line "
            "the base with baking paper. Pour the batter in evenly. Tap the tin gently on the counter "
            "2–3 times to release large air bubbles. Place in your oven preheated to 180 °C (355 °F). "
            "Bake for 28–32 minutes. Check at 28 minutes: insert a toothpick or skewer into the "
            "centre — if it comes out clean or with just a few moist crumbs, it's done. If wet batter "
            "clings to it, give it 4 more minutes then check again."
        ),
        (
            "Remove from the oven and let the cake cool in the tin for 10 minutes — it will shrink "
            "slightly from the sides and become easier to release. Then turn it out onto a wire rack "
            "and let it cool completely (at least 30 minutes). If you frost it while it's still warm, "
            "the ganache will melt and slide off. For chocolate ganache: heat ½ cup (120 ml) of heavy "
            "cream until just simmering, pour over 100 g of finely chopped dark chocolate, let sit "
            "2 minutes, then stir from the centre outward until glossy. Pour over the cooled cake."
        ),
    ],
}


def adapt_steps(steps: list[str], recipe_id: int, skill_level: str) -> list[str]:
    """
    Returns the appropriate step list for the given user skill level.

    For Chef (or any unrecognised level): returns the original steps unchanged.
    For Home Cook: returns the expanded steps from HOME_COOK_STEPS, falling back
    to the original steps for any recipe not in the dictionary.

    This function is intentionally simple — the emotion-based adaptive support
    in cooking_session._send_steps() appends additional text to whichever
    instruction this function selects, so both features compose naturally.
    """
    if skill_level and skill_level.strip().lower() == "home cook":
        expanded = HOME_COOK_STEPS.get(recipe_id)
        if expanded and len(expanded) == len(steps):
            return expanded
        # Fallback: original steps if recipe not in dict or length mismatch
        return steps
    # Chef or unrecognised skill → original steps unchanged
    return steps
