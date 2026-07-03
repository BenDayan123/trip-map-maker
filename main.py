"""Thin entrypoint — delegates to the gmap_planner package pipeline."""

from gmap_planner.pipeline import main

if __name__ == "__main__":
    main()

# streamlit run Home.py