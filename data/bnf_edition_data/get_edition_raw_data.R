# set the working directory
setwd("D:/bnf_edition_data")

# Call the relevant libraries
library(SPARQL)
library(tidyverse)

# For documentation, save the time when the querying started.
writeLines(capture.output(sessionInfo()), paste0("sessionInfo","_of_the_bnf_data_acquisition_run_of_",as.character(Sys.Date()),".txt"))


# Define the function for querying the edition data
get_bnf_edition_data <- function(year){
  
query <- paste0("PREFIX bnf-onto: <http://data.bnf.fr/ontology/bnf-onto/>
PREFIX rdarelationships: <http://rdvocab.info/RDARelationshipsWEMI/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdam: <http://rdaregistry.info/Elements/m/#> 
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
SELECT DISTINCT ?edition ?bnf_id ?title ?year_first ?year_range ?description ?place ?publisher ?work ?digital_copy_link ?subject_topic  ?expression ?language ?record_type ?author ?editor ?translator ?publisher_2 ?illustrator

WHERE {
 ?edition bnf-onto:firstYear ?year_first.
 OPTIONAL {?edition bnf-onto:FRBNF ?bnf_id.} 
 OPTIONAL { ?edition rdam:P30279 ?place.}
 OPTIONAL {?edition dcterms:title ?title.}
 OPTIONAL {?edition rdam:P30176 ?publisher.}
 OPTIONAL {?edition dcterms:description ?description.}
 OPTIONAL {?edition bnf-onto:firstYear ?year_first.}
 OPTIONAL {?edition dcterms:date ?year_range.}
 OPTIONAL {?edition rdarelationships:workManifested ?work.}
 OPTIONAL {?edition rdam:P30016 ?digital_copy_link.}
 OPTIONAL {?edition dcterms:subject ?subject_topic.}
?edition rdarelationships:expressionManifested ?expression.
OPTIONAL {?expression dcterms:language ?language.}		
OPTIONAL {?expression dcterms:type ?record_type.}
OPTIONAL {?expression  marcrel:aut ?author.}
OPTIONAL {?expression  marcrel:edt ?editor.} 
OPTIONAL {?expression  marcrel:trl ?translator.} 
OPTIONAL {?expression  marcrel:pbl ?publisher_2.} 
OPTIONAL {?expression  marcrel:ill ?illustrator.} 
 
FILTER(?year_first = ",as.character(year),").
}")  
results <- SPARQL(url="https://data.bnf.fr/sparql",query=query)
data_table <- results$results
write.csv(data_table,paste0("edition_raw_data_by_year/raw_edition_data_for_the_year_",as.character(year),".csv"),row.names = FALSE)
Sys.sleep(5+runif(n=1)*5) 
rm(data_table)
gc()

}

# Query over the year range
for(i in 1454:1799){
  query <- get_bnf_edition_data(i)
  print(i)
  gc()
}

# Compile the data into a single data frame
list_edition_data <- list.files("edition_raw_data_by_year/",full.names = TRUE)
list_edition_data_combined_data <- do.call(rbind,lapply(list_edition_data,read.csv)) 

# Save the data frame

write.csv(list_edition_data_combined_data,"bnf_edition_data_raw.csv",row.names = FALSE)

# Produce basic statistics about the edition data

n_unique_editions <- list_edition_data_combined_data %>% distinct(edition) %>% nrow(.)

n_with_place_information <- list_edition_data_combined_data %>% filter(!is.na(place) & place!="") %>% distinct(edition) %>% nrow(.)
n_with_record_type_information <- list_edition_data_combined_data %>% filter(!is.na(record_type) & record_type!="") %>% distinct(edition) %>% nrow(.)
n_with_author_information <- list_edition_data_combined_data %>% filter(!is.na(author) & author!="") %>% distinct(edition) %>% nrow(.)
n_with_language_information <- list_edition_data_combined_data %>% filter(!is.na(language) & language!="") %>% distinct(edition) %>% nrow(.)