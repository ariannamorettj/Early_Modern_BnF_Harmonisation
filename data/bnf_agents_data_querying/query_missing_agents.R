# Call relevant libraries
library(tidyverse)
library(magrittr)
library(SPARQL)
# Set the path to the folder here
setwd("D:/bnf_agents_data_querying")

# Define the functiom to query author information for specific author in the BNF
get_bnf_data_for_actor <- function(actor,file_name){
  query <- paste0('PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
PREFIX bnf-onto: <http://data.bnf.fr/ontology/bnf-onto/>
PREFIX rdarelationships: <http://rdvocab.info/RDARelationshipsWEMI/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdam: <http://rdaregistry.info/Elements/m/#> 
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/> 
PREFIX bio: <http://vocab.org/bio/0.1/> 
PREFIX skos: <http://www.w3.org/2004/02/skos/core#> 
SELECT DISTINCT ?actor_birth ?actor_name ?actor_first_name ?actor_last_name ?entity_type ?first_year ?actor_country ?actor_language ?actor_gender ?actor_profession  ?actor_death ?actor_start ?actor_end ?actor_link_exact ?actor_link_close

WHERE {
 OPTIONAL {' ,as.character(actor),' foaf:name ?actor_name.} 
 OPTIONAL {' ,as.character(actor),' foaf:givenName ?actor_first_name.}
 OPTIONAL {' ,as.character(actor),' foaf:familyName ?actor_last_name.}
 OPTIONAL {' ,as.character(actor),' rdf:type ?entity_type.}
 OPTIONAL {' ,as.character(actor),' bnf-onto:firstYear ?first_year.}  
 OPTIONAL {' ,as.character(actor), ' bio:birth  ?actor_birth.}
 OPTIONAL { ' ,as.character(actor), ' rdagroup2elements:countryAssociatedWithThePerson  ?actor_country.}
 OPTIONAL { ' ,as.character(actor), ' rdagroup2elements:languageOfThePerson ?actor_language.}
 OPTIONAL { ' ,as.character(actor), ' foaf:gender ?actor_gender. }
 OPTIONAL { ' ,as.character(actor), ' rdagroup2elements:biographicalInformation ?actor_profession.}
 OPTIONAL { ' ,as.character(actor), ' bio:birth ?actor_birth.}
 OPTIONAL { ' ,as.character(actor), ' bio:death ?actor_death.}
 OPTIONAL { ' ,as.character(actor), ' bnf-onto:firstYear ?actor_start. } 
 OPTIONAL { ' ,as.character(actor), ' bnf-onto:lastYear ?actor_end.  }  
 OPTIONAL { 
    ?person foaf:focus ' ,as.character(actor), '.
    ?person skos:exactMatch ?actor_link_exact.}
 OPTIONAL { 
    ?person foaf:focus ' ,as.character(actor), '.
    ?person skos:closeMatch ?actor_link_close.}
 }')
  
  results <- SPARQL(url="https://data.bnf.fr/sparql",query=query)
  data_table <- results$results
  if(nrow(data_table)!=0){
    write.csv(cbind.data.frame(actor=actor,data_table),file=paste0("actor_queries_results/",file_name,".csv",collapse = ""),row.names = FALSE)
  }
  Sys.sleep(1+runif(n=1)*1) 
}

# Define a function that reads a csv and adds the name of the file as a column to the data frame
read_csv_and_supplement_file <- function(file){
  data <- read.csv(file)
  data_final <- cbind.data.frame(identifier_column=file,data)
  return(data_final)
  
}

# Subset the actors of the new edition data

bnf_editions_new <- read.csv("bnf_edition_data_raw.csv")

bnf_editions_actors <- unique(c(bnf_editions_new$author,bnf_editions_new$editor,bnf_editions_new$illustrator,bnf_editions_new$illustrator,bnf_editions_new$publisher_2,bnf_editions_new$translator)) %>% as.data.frame(.)
colnames(bnf_editions_actors) <- "actor"
bnf_editions_actors <- bnf_editions_actors %>% filter(!is.na(actor))

# Query the actor data for all of the missing actors

for(i in 109494:nrow(bnf_editions_actors)){
  
  try(get_bnf_data_for_actor(paste0("",as.character(bnf_editions_actors$actor[i]),""),paste0("actor_file_",as.character(i),collapse="")))
  print(i)
}


list_actors<- list.files("actor_queries_results/",full.names = TRUE)
list_actors_data <- do.call(rbind,lapply(list_actors,read.csv)) 
write.csv(list_actors_data,"actor_data.csv",row.names = FALSE)
