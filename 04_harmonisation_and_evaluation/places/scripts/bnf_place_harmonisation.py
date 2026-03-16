import pandas as pd
import numpy as np
import re
import os

# Set the working directory to the data/bnf_place_harmonisation directory
# This assumes the script is in data/bnf_place_harmonisation/scripts/
script_dir = os.path.dirname(os.path.abspath(__file__))
working_dir = os.path.dirname(script_dir)
os.chdir(working_dir)

print(f"Working directory set to: {os.getcwd()}")


def str_after_last_parentheses(x):
    """
    Parse city-level and country-level place information from a string.
    Extracts text before and after the last set of parentheses.
    """
    if pd.isna(x) or x == "":
        return ["", ""]

    # Find all occurrences of opening parentheses
    matches = [m.start() for m in re.finditer(r'\(', x)]

    if not matches:
        # No parentheses found
        return [x.strip(), ""]

    # Get the position of the last opening parenthesis
    x_loc_max = max(matches)
    n_string = len(x)

    # Extract substring after last parenthesis
    sub_string_after_last = x[x_loc_max:n_string]
    sub_string_after_last = re.sub(r'[\(\)]', '', sub_string_after_last).strip()

    # Extract substring before last parenthesis
    sub_string_before_last = x[:x_loc_max].strip()

    return [sub_string_before_last, sub_string_after_last]


# For documentation: Publication place data matched between the HPB and TGN was used to create
# a raw (e.g. prior to manual curation version) of the harmonisation table for publication
# place information, the silenced code documents this.
# publication_place_strings_to_tgn_ids = pd.read_csv("data/data_work/hpb_place_string_to_geo_id_links.csv")
# publication_place_strings_to_tgn_ids.rename(columns={publication_place_strings_to_tgn_ids.columns[0]: "city_harmonised"}, inplace=True)
# tgn_ids_to_tgn_metadata = pd.read_csv("data/data_work/hpb_geo_id_to_geo_data.csv")

# Download the raw edition data
bnf_raw_edition_data = pd.read_csv("bnf_edition_data_raw.csv")

# Subset the place information
bnf_raw_edition_data_place = bnf_raw_edition_data[['edition', 'place']].drop_duplicates()

# Parse the city-level and country-level publication place information
bnf_raw_edition_data_unique_places = (bnf_raw_edition_data_place
                                      .groupby('place')
                                      .size()
                                      .reset_index(name='n')
                                      .sort_values('n', ascending=False)
                                      .reset_index(drop=True))

bnf_raw_edition_data_unique_places['country'] = ""
bnf_raw_edition_data_unique_places['city'] = ""

# Apply the parsing function to each unique place
for i in range(len(bnf_raw_edition_data_unique_places)):
    city_and_country_information = str_after_last_parentheses(
        bnf_raw_edition_data_unique_places.loc[i, 'place']
    )
    bnf_raw_edition_data_unique_places.loc[i, 'city'] = city_and_country_information[0]
    bnf_raw_edition_data_unique_places.loc[i, 'country'] = city_and_country_information[1]

# Save all country-level values
bnf_raw_edition_data_unique_countries = (bnf_raw_edition_data_unique_places
                                         .groupby('country')
                                         .size()
                                         .reset_index(name='n')
                                         .sort_values('n', ascending=False))
# bnf_raw_edition_data_unique_countries.to_csv("data/data_work/bnf_unique_raw_country_values.csv", index=False)

# Harmonise the publication place city-level information
bnf_raw_edition_data_unique_places['brackets'] = bnf_raw_edition_data_unique_places['city'].str.contains(r'[\[\]]',
                                                                                                         regex=True)
bnf_raw_edition_data_unique_places['parentheses'] = bnf_raw_edition_data_unique_places['city'].str.contains(r'[\(\)]',
                                                                                                            regex=True)
bnf_raw_edition_data_unique_places['question_marks'] = bnf_raw_edition_data_unique_places['city'].str.contains(r'\?',
                                                                                                               regex=True)
bnf_raw_edition_data_unique_places['city_harmonised'] = bnf_raw_edition_data_unique_places['city']

# Chain of string replacements for harmonisation
bnf_raw_edition_data_unique_places['city_harmonised'] = (
    bnf_raw_edition_data_unique_places['city_harmonised']
        .str.replace(r'[\[\]]', '', regex=True)
        .str.replace(r'[\(\)]', '', regex=True)
        .str.replace(r'\?', '', regex=True)
        .str.replace(',', '', regex=False)
        .str.replace('In ', '', regex=False)
        .str.replace('A ', '', regex=False)
        .str.replace('À ', '', regex=False)
        .str.replace('Tot ', '', regex=False)
        .str.replace('Te ', '', regex=False)
        .str.replace("T' ", '', regex=False)
        .str.replace('t ', '', regex=False)
        .str.replace("t' ", '', regex=False)
        .str.strip()
)

# Get the unique harmonised values
bnf_raw_edition_data_unique_places_harmonised = (
    bnf_raw_edition_data_unique_places
        .groupby('city_harmonised')['n']
        .sum()
        .reset_index()
        .sort_values('n', ascending=False)
        .reset_index(drop=True)
)

# For documentation: Publication place data matched between the HPB and TGN...
# bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids = (
#     bnf_raw_edition_data_unique_places_harmonised
#     .merge(publication_place_strings_to_tgn_ids, how='left')
#     .merge(tgn_ids_to_tgn_metadata, how='left')
# )
# bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids_top_2000 = (
#     bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids
#     .sort_values('n', ascending=False)
#     .drop_duplicates(subset=['city_harmonised', 'tgn_id', 'publication_place',
#                              'publication_country', 'longitude', 'latitude'])
#     .head(2000)
# )
# bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids_top_2000.to_csv(
#     "data/data_work/bnf_place_name_harmonisation_table.csv", index=False
# )

# Download a manually curated harmonisation table
bnf_harmonised_publication_places_mapped_to_tgn = pd.read_csv(
    "data/data_work/bnf_place_name_harmonisation_table_final.csv"
)

# Map the tgn identifiers to the BNF data
bnf_raw_edition_data_mapped_to_tgn = (
    bnf_raw_edition_data_place
        .merge(bnf_raw_edition_data_unique_places, on='place', how='left')
        .merge(bnf_harmonised_publication_places_mapped_to_tgn, on='city_harmonised', how='left')
        .drop_duplicates(subset=['edition', 'place', 'brackets', 'parentheses', 'question_marks',
                                 'tgn_id', 'publication_place', 'publication_country', 'longitude', 'latitude'])
)

# Rename the columns
bnf_raw_edition_data_mapped_to_tgn.columns = [
    'edition', 'place_original', 'n', 'country', 'city', 'brackets', 'parentheses',
    'question_marks', 'city_harmonised', 'tgn_id', 'publication_place',
    'publication_country', 'longitude', 'latitude'
]

# Keep only necessary columns
bnf_raw_edition_data_mapped_to_tgn = bnf_raw_edition_data_mapped_to_tgn[[
    'edition', 'place_original', 'brackets', 'parentheses', 'question_marks',
    'tgn_id', 'publication_place', 'publication_country', 'longitude', 'latitude'
]]

# Rename columns to be more informative
bnf_raw_edition_data_mapped_to_tgn.columns = [
    'edition', 'place_original', 'place_uncertainty_brackets',
    'place_uncertainty_parentheses', 'place_uncertainty_question_marks',
    'tgn_id', 'publication_place', 'publication_country', 'longitude', 'latitude'
]

# Create final version by taking first occurrence for each edition
bnf_edition_data_with_place_information = (
    bnf_raw_edition_data_mapped_to_tgn
        .groupby('edition')
        .first()
        .reset_index()
)

# Download all harmonised country-level values
bnf_harmonised_publication_countries = (
    pd.read_csv("data/data_work/bnf_country_harmonisation_table.csv")
        .drop_duplicates(subset=['country', 'country_harmonised'])
)

# Use harmonisation table for publication country information
bnf_publication_countries = (
    bnf_raw_edition_data_place
        .merge(bnf_raw_edition_data_unique_places, on='place', how='left')
        .merge(bnf_harmonised_publication_countries, on='country', how='left')
)

bnf_publication_countries_aggregates = (
    bnf_publication_countries
        .groupby('country_harmonised')
        .size()
        .reset_index(name='n')
)

# Create the final version of the publication country data
bnf_publication_countries_final_data = (
    bnf_publication_countries
        .groupby('edition')['country_harmonised']
        .first()
        .reset_index()
        .rename(columns={'country_harmonised': 'publication_country_alternative'})
)

# Merge the publication country data to the harmonised city-level information
bnf_edition_data_with_place_information_final = (
    bnf_edition_data_with_place_information
        .merge(bnf_publication_countries_final_data, on='edition', how='left')
)

# Use TGN country by default, fall back to alternative if missing
bnf_edition_data_with_place_information_final['publication_country'] = np.where(
    bnf_edition_data_with_place_information_final['publication_country'].notna(),
    bnf_edition_data_with_place_information_final['publication_country'],
    bnf_edition_data_with_place_information_final['publication_country_alternative']
)

# Drop the alternative column
bnf_edition_data_with_place_information_final = (
    bnf_edition_data_with_place_information_final
        .drop(columns=['publication_country_alternative'])
)

# Save the final place data
bnf_edition_data_with_place_information_final.to_csv(
    "data/data_final/bnf_publication_place.csv",
    index=False
)

print("Processing complete! Final data saved to data/data_final/bnf_publication_place.csv")