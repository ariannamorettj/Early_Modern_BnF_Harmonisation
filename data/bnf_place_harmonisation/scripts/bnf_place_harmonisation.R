# Call relevant libraries
library(tidyverse)
library(magrittr)
library(SPARQL)
# Set the path to the folder here
setwd("D:/bnf_place_harmonisation")

# Define a function for parsing city-level and country-level place information

str_after_last_parentheses <- function(x){
  
  x_loc <- str_locate_all(x,pattern = "\\(") %>% unlist(.)
  
  x_loc_max <- max(x_loc)
  
  n_string <- nchar(x)
  
  sub_string_after_last <- str_sub(x,x_loc_max,n_string) %>% gsub(x=.,pattern="\\(|\\)",replacement="") %>% trimws(.)
  
  if(is.na(x_loc_max) | is.null(x_loc_max)|is.infinite(x_loc_max)){
    x_loc_max <- nchar(x)
  }
  
  sub_string_before_last <- str_sub(x,1,x_loc_max-1) %>% trimws(.)
  
  return(c(sub_string_before_last,sub_string_after_last))
}

# For documentation: Publication place data matched between the HPB and TGN was used to create a raw (e.g. prior to manual curation version) of the harmonisation
# table for publication place information, the silenced code documents this.

#publication_place_strings_to_tgn_ids <- read.csv("data/data_work/hpb_place_string_to_geo_id_links.csv")
#colnames(publication_place_strings_to_tgn_ids)[1] <- "city_harmonised" 
#tgn_ids_to_tgn_metadata <- read.csv("data/data_work/hpb_geo_id_to_geo_data.csv")

# Download the raw edition data

bnf_raw_edition_data <- read.csv("bnf_edition_data_raw.csv")

# Subset the place information

bnf_raw_edition_data_place <- bnf_raw_edition_data %>% distinct(edition,place) 

# Parse the city-level and country-level publication place information from the unique publication place values

bnf_raw_edition_data_unique_places <- bnf_raw_edition_data_place %>% count(place) %>% arrange(-n) %>% mutate(country="") %>% mutate(city="")
for(i in 1:nrow(bnf_raw_edition_data_unique_places)){
  city_and_country_information <- str_after_last_parentheses(bnf_raw_edition_data_unique_places$place[i])
  bnf_raw_edition_data_unique_places$city[i] <- city_and_country_information[1]
  bnf_raw_edition_data_unique_places$country[i] <- city_and_country_information[2]
}
# Save all country-level values
bnf_raw_edition_data_unique_countries <- bnf_raw_edition_data_unique_places %>% count(country) %>% arrange(-n)
#write.csv(bnf_raw_edition_data_unique_countries,"data/data_work/bnf_unique_raw_country_values.csv",row.names = FALSE)

# Harmonise the publication place city-level information
bnf_raw_edition_data_unique_places <- bnf_raw_edition_data_unique_places %>%
  mutate(brackets=grepl(x=city,pattern="\\[|\\]")) %>% 
  mutate(parentheses=grepl(x=city,pattern="\\(|\\)")) %>%
  mutate(question_marks=grepl(x=city,pattern="\\?")) %>%
  mutate(city_harmonised=city) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="\\[|\\]",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="\\(|\\)",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="\\?",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern=",",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="In ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="A ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="À ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="Tot ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="Te ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="T' ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="t ",replacement="")) %>%
  mutate(city_harmonised=gsub(x=city_harmonised,pattern="t' ",replacement="")) %>%
  mutate(city_harmonised=trimws(city_harmonised)) 

# Get the unique harmonised values
bnf_raw_edition_data_unique_places_harmonised <- bnf_raw_edition_data_unique_places %>% count(city_harmonised,wt=n) %>% arrange(-n)

#bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids <- bnf_raw_edition_data_unique_places_harmonised %>%
#left_join(publication_place_strings_to_tgn_ids) %>%
#left_join(tgn_ids_to_tgn_metadata)  

#bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids_top_2000 <- bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids %>% arrange(-n) %>% distinct(city_harmonised,tgn_id,publication_place,publication_country,longitude,latitude) %>% .[1:2000,]
#write.csv(bnf_raw_edition_data_unique_places_harmonised_mapped_to_tgn_ids_top_2000,"data/data_work/bnf_place_name_harmonisation_table.csv",row.names = FALSE)


# Download a manually curated harmonisation table that maps tgn identifiers to common publication places in BNF
bnf_harmonised_publication_places_mapped_to_tgn <- read.csv("data/data_work/bnf_place_name_harmonisation_table_final.csv")

# Map the tgn identifiers to the BNF data
bnf_raw_edition_data_mapped_to_tgn <- bnf_raw_edition_data_place %>% 
  left_join(bnf_raw_edition_data_unique_places) %>% 
  left_join(bnf_harmonised_publication_places_mapped_to_tgn) %>%
  distinct(edition,place,brackets,parentheses,question_marks,tgn_id,publication_place,publication_country,longitude,latitude)
# Rename the columns of the resulting data set to be more informative
colnames(bnf_raw_edition_data_mapped_to_tgn) <- c("edition","place_original","place_uncertainty_brackets","place_uncertainty_parentheses","place_uncertainty_question_marks","tgn_id","publication_place","publication_country","longitude","latitude")

# Create an almost finished version of the BNF publication place data by ensuring that each edition is in the data
# set only once (the lazy solution is not terribly problematic given the fact that there are only a few editions that break this rule)
bnf_edition_data_with_place_information <- bnf_raw_edition_data_mapped_to_tgn %>% 
group_by(edition) %>% 
summarise(place_original=place_original[1],place_uncertainty_brackets=place_uncertainty_brackets[1],place_uncertainty_parentheses=place_uncertainty_parentheses[1],place_uncertainty_question_marks=place_uncertainty_question_marks[1],tgn_id=tgn_id[1],publication_place=publication_place[1],publication_country=publication_country[1],longitude=longitude[1],latitude=latitude[1]) %>%
as.data.frame(.)  

# Download all harmonised country-level values extracted from the original publication place information
bnf_harmonised_publication_countries <- read.csv("data/data_work/bnf_country_harmonisation_table.csv") %>% distinct(country,country_harmonised)

# Use bnf_harmonised_publication_countries to harmonise the publication country information
bnf_publication_countries <- bnf_raw_edition_data_place %>% left_join(bnf_raw_edition_data_unique_places) %>% left_join(bnf_harmonised_publication_countries)
bnf_publication_countries_aggregates <- bnf_publication_countries %>% count(country_harmonised)

# Create the final version of the publication country data.
bnf_publication_countries_final_data <- bnf_publication_countries %>% group_by(edition) %>% summarise(.,publication_country_alternative=country_harmonised[1]) %>% as.data.frame(.)

# Merge the publication country data to the harmonised city-level information. The country information obtained by tgn will be used by default, but in cases in which it is missing we will use the publication country information from the BNF
bnf_edition_data_with_place_information_final <- bnf_edition_data_with_place_information %>% 
left_join(bnf_publication_countries_final_data) %>%
mutate(publication_country=ifelse(!is.na(publication_country),publication_country,publication_country_alternative)) %>%
mutate(publication_country_alternative=NULL)  

# Save the final place data
write.csv(bnf_edition_data_with_place_information_final,"data/data_final/bnf_publication_place.csv",row.names = FALSE)
