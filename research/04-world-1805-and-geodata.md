# 04 - World in 1805 and open geodata sources

Scope: (A) polities to represent worldwide circa 1805, (B) open geodata for terrain, borders, rivers, climate, cities, (C) projection notes.

## 0. Method and confidence

- Research tools: WebSearch only produced usable results. **WebFetch was blocked by a PreToolUse hook in this session**, so no page could be read in full. Every web-derived claim below comes from search-result snippets, with the source URL named. Items marked **[unverified-web]** come from my background knowledge and were not confirmed in this session. Verify them before relying on them.
- Historical confidence tags: **[H]** well established, **[M]** established but details (exact date, name, extent) vary by source, **[L]** weak or contested, so treat it as a design choice.
- Region counts are proposals in two profiles: **Full** (richer) and **Lean** (compressed). See section A.8 for why two exist.

---

## A. Polities and factions circa 1805

### A.0 Reference: vanilla scale (what we are extending)

| Fact | Value | Source / status |
|---|---|---|
| Napoleon TW Grand Campaign (1805) factions | 5 playable, 18 non-playable, 16 "emerging" via liberation or revolution | Total War Wiki, https://wiki.totalwar.com/w/Factions_in_Napoleon:_Total_War.html (search snippet) |
| Napoleon TW Grand Campaign map | "74 regions, all in Europe" | TWC Wiki via search snippet, https://wiki.twcenter.net/index.php?title=Napoleon%3A_Total_War. **Not confirmed**, a second search could not corroborate it. Treat as roughly 70-100. |
| Napoleon TW Europe campaign win goal | 35 regions | Fandom wiki, https://totalwar.fandom.com/wiki/France_(Napoleon:_Total_War) (snippet) |
| Empire TW campaign theatres | 3 main (Europe, Americas, India) + 4 sea-only trade theatres (Brazilian Coast, Ivory Coast, Straits of Madagascar, West Indies) | https://totalwar.fandom.com/wiki/Empire:_Total_War ; https://wiki.twcenter.net/index.php?title=Empire%3A_Total_War |
| Empire TW total region count | **No authoritative figure found.** A TWC modding guide says "ETW currently has **205 regions**, this means we can add up to **41 regions**" (about 6,000 days old). That implies a hard cap near **246**. | https://www.twcenter.net/threads/guide-to-the-etw-map.355187/ (snippet). **The brief's "~130" is not supported; 205 may include sea or unexplorable regions.** |
| Empire region structure | each region has a capital settlement plus separate ports, towns, farms | search snippet, https://www.giantbomb.com/games/3030-20509/ |
| Where to get the true count | count entries in the game's region data (a TWC guide says `CAI_world_regions` / `regions.esf` hold all regions) | https://www.twcenter.net/threads/guide-to-the-etw-map.355187/ |

**Design-critical flag:** if Napoleon shares Empire's roughly 246-region ceiling (**unverified**, same engine family), the whole mod must fit in about 240 regions including Europe. Section A.8 plans for this. **Action: count regions in the actual NTW startpos and test-add regions before committing to a budget.**

### A.1 Americas

Roles: **P** = playable (suggested), **AI-M** = AI major, **AI-m** = AI minor, **Rebel** = unaligned/rebel/native hold-out region. "Colony of X" regions belong to the parent faction, not a separate faction.

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| United States | Washington, D.C. (seat since 1800) | Atlantic seaboard to the Mississippi; Louisiana Purchase nominal | P (stretch) or AI-M | 7 | 5 | Louisiana Purchase signed Apr 1803, transfer Dec 1803 [H]. Jefferson's 2nd term from Mar 1805 [H]. Lewis and Clark expedition 1804-06 [H]. First Barbary War ends Jun 1805 [H]. |
| British North America (Britain) | Quebec; York; Halifax | Lower/Upper Canada, Maritimes, HBC/NWC fur interior | Britain colony | 4 | 3 | Hudson's Bay Co. and North West Co. rivalry [H]. |
| Spain: New Spain | Mexico City | Mexico, Provincias Internas (Texas to Sonora, New Mexico), Californias, Florida | Spain colony | 7 | 5 | Viceroyalty of New Spain [H]. East and West Florida remain Spanish [H]. Mexican independence begins Sept 1810 [H]. |
| Spain: Guatemala | Guatemala City | Captaincy-General, Central America | Spain colony | 1 | 1 | [H] |
| Spain: Caribbean | Havana; San Juan; Santo Domingo | Cuba, Puerto Rico, eastern Hispaniola | Spain colony | 3 | 2 | Santo Domingo ceded to France 1795 (Basel), under French/Haitian pressure 1801-09 [M]. |
| Spain: Tierra Firme | Caracas; Bogota; Quito | Venezuela, New Granada, Quito | Spain colony | 3 | 2 | Miranda's expedition 1806 [M]. |
| Spain: Peru | Lima | Lima, Cuzco/Arequipa, Upper Peru (Charcas) | Spain colony | 3 | 2 | Viceroyalty of Peru [H]. |
| Spain: Chile | Santiago | Captaincy-General of Chile | Spain colony | 1 | 1 | [H] |
| Spain: Rio de la Plata | Buenos Aires | Buenos Aires, Banda Oriental (Montevideo), Paraguay | Spain colony | 3 | 2 | Viceroyalty est. 1776 [H]. British invasions of Buenos Aires 1806-07 [H]. |
| Portugal: Brazil | Rio de Janeiro (colonial capital since 1763) | Coast to Minas, Mato Grosso, Para/Maranhao | Portugal colony | 6 | 4 | Court flees to Rio Nov 1807 [H], so it is not yet there in 1805. |
| France: Caribbean and Guiana | Fort-Royal; Basse-Terre; Cayenne | Martinique, Guadeloupe, French Guiana | France colony | 3 | 2 | Saint-Lucia British since 1803 [M]. Martinique falls to Britain 1809 [H]. |
| Haiti | Port-au-Prince (Dessalines ruled from Marchand) [M] | western Hispaniola | **AI-m** (new state) | 2 | 1 | Independence declared 1 Jan 1804 [H]. Dessalines emperor Oct 1804 [H]. |
| British Caribbean and Guiana | Kingston; Bridgetown | Jamaica, Windwards/Leewards, Bahamas, Demerara-Essequibo, Belize/Mosquito | Britain colony | 5 | 3 | Dutch Guiana colonies captured 1803 [M]. Trinidad British since 1797 [H]. |
| Dutch (Batavian Republic) Americas | Paramaribo; Willemstad | Suriname, Curacao and leeward islands | Netherlands colony | 2 | 1 | Suriname re-occupied by Britain 1804 [M]. Batavian Republic lasts to Jun 1806 [H]. |
| Denmark: Atlantic | Charlotte Amalie; Godthaab | Danish West Indies (St Croix/Thomas/John), Greenland | Denmark colony | 2 | 1 | Danish West Indies seized by Britain 1807 [H]. Iceland is counted in Europe. |
| Sweden: Saint-Barthelemy | Gustavia | one island | fold into minor | 0 | 0 | Swedish since 1784 [H]. Too small to be a region. |
| Russian America | Sitka (re-founded 1804) | Alaska, Kodiak | Russia colony | 1 | 1 | Battle of Sitka Oct 1804 [H]. Fort Ross is later, 1812. |
| Indigenous: Great Lakes/Ohio confederacy | none | Shawnee, Miami, Ojibwe, Haudenosaunee | Rebel | 1 | 1 | Greenville Treaty 1795 [H]. Tenskwatawa's movement 1805-06, Tecumseh later [M]. |
| Indigenous: Southeast confederacies | none | Creek, Cherokee, Choctaw, Chickasaw | Rebel | 1 | 1 | [H] |
| Indigenous: Great Plains | none | Lakota, Comanche (Comancheria), Apache | Rebel | 2 | 1 | [H] |
| Indigenous: Pacific NW and interior | none | Nootka, Chinook, Salish, Great Basin | Rebel | 1 | 1 | [H] |
| Mapuche (Araucania) | none | southern Chile independent zone | Rebel | 1 | 1 | Never conquered by Spain [H]. |
| Amazon and Orinoco interior | none | uncontrolled hinterland | Rebel | 1 | 1 | [H] |
| Pampas and Patagonia | none | Tehuelche, Ranquel, Pampa | Rebel | 1 | 0 | [H] |

### A.2 Africa

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| Egypt (Ottoman province, de facto autonomous) | Cairo | Nile valley; Mamluk beys hold Upper Egypt | AI-M (could be P) | 2 | 1 | French left 1801 [H]. Muhammad Ali becomes wali in 1805 (elected by ulama in May, confirmed by the Porte in July) [M]. |
| Tripolitania (Karamanli) | Tripoli | Tripolitania, Fezzan, Cyrenaica | AI-m | 1 | 1 | Yusuf Karamanli [H]. US war 1801-05, Derna Apr 1805 [H]. |
| Tunis (Husainid Beylik) | Tunis | Tunisia | AI-m | 1 | 1 | Hammuda Pasha [M]. |
| Regency of Algiers | Algiers | coast to Constantine/Oran | AI-m | 2 | 1 | Dey; Ottoman nominal [H]. |
| Morocco (Alawi sultanate) | Fez / Marrakesh | Morocco | AI-m | 2 | 1 | Sultan Sulayman [M]. |
| Sokoto Caliphate | Sokoto / Gwandu | Hausa lands, northern Nigeria | AI-m (new, emerging) | 2 | 1 | Founded Feb 1804 by Usman dan Fodio [H]. Kebbi captured 1805; Gobir falls 1808, https://en.wikipedia.org/wiki/Sokoto_Caliphate (snippet). |
| Bornu (Kanem-Bornu) | Ngazargamu | Lake Chad basin | AI-m | 1 | 1 | Al-Kanemi rises c.1808 [M]. |
| Darfur and Wadai | El Fasher; Wara | central Sudan | Rebel/AI-m | 1 | 1 | [H] |
| Sennar (Funj) and Kordofan | Sennar | Nile above Egypt | AI-m | 1 | 1 | Funj sultanate in decline [H]. |
| Oyo (Yoruba) | Oyo-Ile | SW Nigeria | AI-m | 1 | 1 | Oyo is weakening; major break c.1817 [L-M]. |
| Dahomey | Abomey | Benin | AI-m | 1 | 0 | King Adandozan [M]. |
| Asante | Kumasi | Gold Coast hinterland | AI-m | 1 | 1 | [H] |
| Segu / Bambara and Masina | Segou | Niger bend | Rebel | 1 | 1 | Masina jihad is 1818, later [H]. |
| Futa Jallon / Futa Toro imamates | Timbo | upper Senegal/Guinea | Rebel | 1 | 0 | [H] |
| Ethiopia (Zemene Mesafint) | Gondar | highlands; Ras Wolde Selassie in Tigray | AI-m (fragmented) | 2 | 1 | "Era of the Princes" 1769-1855 [H]. |
| Zanzibar/Omani East Africa | Zanzibar | Swahili coast | AI-m (under Oman) | 1 | 1 | Sayyid Said sole ruler 1806 [M]. |
| Great Lakes kingdoms | Mengo | Buganda, Bunyoro | Rebel | 1 | 1 | [H] |
| Congo, Lunda, Luba | Mbanza Kongo; Musumba | central Africa | Rebel | 1 | 1 | [H] |
| Madagascar (Merina) | Antananarivo | central highlands | AI-m | 1 | 1 | Andrianampoinimerina unifies Imerina, d.1810 [M]. |
| Portugal: Angola | Luanda | coast | Portugal colony | 1 | 1 | [H] |
| Portugal: Mozambique | Mozambique Island | coast | Portugal colony | 1 | 1 | [H] |
| Cape Colony | Cape Town | Cape + Eastern frontier | Netherlands (Batavian) then Britain | 2 | 1 | Batavian from 1803; British capture at Blaauwberg Jan 1806 [H]. |
| Southern African interior | none | Xhosa, Zulu/Mthethwa, Sotho-Tswana | Rebel | 2 | 1 | Shaka is later, 1816 [H]. |
| France: Senegal | Saint-Louis; Goree | coast | France colony | 1 | 1 | [M] |
| France: Mascarenes | Port-Louis (Isle de France) | Mauritius, Reunion | France colony | 1 | 1 | Mauritius falls to Britain 1810 [H]. |
| Guinea Coast forts | Freetown; Cape Coast | Sierra Leone, Gold Coast forts (Britain/Netherlands/Denmark) | Britain/Denmark/Netherlands | 1 | 1 | Danish Gold Coast and Dutch Elmina forts [H]. |

### A.3 Middle East

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| Ottoman Asia: Anatolia | Konya / Erzurum (Istanbul is Europe) | Anatolia, Armenia highlands | Ottoman (AI-M, or P) | 3 | 2 | Selim III (1789-1807), Nizam-i Cedid reforms [H]. Serbian uprising Feb 1804 (Europe side) [H]. |
| Ottoman Asia: Syria | Damascus / Aleppo | Syria | Ottoman | 2 | 1 | [H] |
| Ottoman Asia: Acre | Acre | Palestine and Lebanon coast | Ottoman | 1 | 1 | Jazzar Pasha d.1804 [M]. |
| Ottoman Asia: Iraq | Baghdad; Mosul | Mesopotamia, Kurdistan | Ottoman (Mamluk governors) | 2 | 2 | [H] |
| Hejaz | Mecca / Medina | west Arabia | Ottoman nominal | 1 | 1 | Wahhabis take Mecca 1803, Medina 1805, Ottomans retake 1812-13 [M-H]. |
| Emirate of Diriyah (1st Saudi state) | Diriyah | Najd | AI-m | 1 | 1 | Wahhabi expansion [H]. |
| Oman (Muscat) | Muscat | SE Arabia | AI-m | 1 | 1 | Sultan Sayyid Said 1806 [M]. |
| Yemen | Sana'a | Imamate | Rebel | 1 | 1 | [H] |
| Eastern Arabia | Manama; Kuwait | Bahrain, Kuwait | Rebel | 1 | 0 | [M] |
| Persia (Qajar) | Tehran | Persia, Azerbaijan, Khorasan | **P (stretch) or AI-M** | 4 | 4 | Fath-Ali Shah; Russo-Persian War 1804-13 [H]. Abbas Mirza at Tabriz [H]. |
| Caucasus: Georgia and khanates | Tbilisi | Kartli-Kakheti, Karabakh, Baku, Erivan | Russia/Persia contested | 2 | 1 | Georgia annexed by Russia Sept 1801 [H]. |

### A.4 South and Central Asia

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| EIC Bengal Presidency | Calcutta | Bengal, Bihar, Orissa (Cuttack 1803) | Britain (EIC) | 2 | 1 | Cornwallis returns as Governor-General 1805, dies Oct 1805 [M]. |
| EIC Ceded and Conquered Provinces | Agra / Delhi | Doab, Delhi region | Britain (EIC) | 1 | 1 | Delhi taken Sept 1803 [H]. Emperor Shah Alam II under British protection [H]. |
| EIC Madras Presidency | Fort St George | Carnatic, Northern Circars, Mysore territories | Britain (EIC) | 2 | 1 | Tipu Sultan fell 1799 [H]. |
| EIC Bombay Presidency | Bombay | Gujarat coast, Malabar | Britain (EIC) | 1 | 1 | [H] |
| Mysore | Mysore | restored Wodeyar | AI-m subsidiary | 1 | 1 | [H] |
| Hyderabad (Nizam) | Hyderabad | Deccan | AI-m subsidiary | 1 | 1 | Subsidiary alliance 1798/1800 [M]. |
| Awadh | Lucknow | Awadh | AI-m subsidiary | 1 | 1 | Cession of Rohilkhand and lower Doab 1801 [M]. |
| Travancore and Cochin | Trivandrum | SW coast | AI-m | 1 | 0 | [H] |
| Maratha: Peshwa and Gaekwad | Pune; Baroda | Konkan, Maharashtra, Gujarat | AI-M | 1 | 1 | Treaty of Bassein Dec 1802 [H]. The Peshwa is reduced to a Company vassal [M]. |
| Maratha: Scindia | Gwalior / Ujjain | Malwa, north | AI-M | 1 | 1 | Surji-Anjangaon 1803 cedes the Doab and Delhi region, Broach [H]. |
| Maratha: Holkar | Indore | Malwa | AI-M | 1 | 1 | Holkar fights on after the others make peace; Rajghat 24 Dec 1805 [M]. |
| Maratha: Bhonsle | Nagpur | central India | AI-m | 1 | 1 | Deogaon 1803 cedes Cuttack and Balasore [H]. |
| Rajputana | Jaipur; Jodhpur; Udaipur | Rajasthan | AI-m | 1 | 1 | [H] |
| Sikh Empire (Punjab) | Lahore | Punjab | AI-M | 1 | 1 | Ranjit Singh took Lahore 1799, Maharaja Apr 1801 [H-M]. Treaty with Britain 1809, later. |
| Nepal (Gorkha) | Kathmandu | Himalaya | AI-m | 1 | 1 | Anglo-Nepalese War 1814, later [H]. |
| Assam, Manipur, NE | Jorhat | Brahmaputra valley | Rebel | 1 | 0 | [M] |
| Sindh and Baluchistan | Hyderabad (Sindh); Kalat | Talpur, Khanate of Kalat | AI-m | 1 | 1 | [H] |
| Durrani Afghanistan | Kabul; Kandahar; Peshawar | Afghan | AI-M (fragmenting) | 2 | 1 | Shah Shuja (1803-09), civil wars [M]. |
| Ceylon | Colombo; Kandy | British coast + Kingdom of Kandy | Britain / Kandy AI-m | 2 | 1 | Ceylon a Crown colony after Amiens 1802 [H]. Kandy falls 1815 [H]. |
| Portuguese Goa | Goa | enclave | Portugal colony | 1 | 0 | [H] |
| Bukhara Emirate | Bukhara | Transoxiana | AI-m | 1 | 1 | Manghit dynasty [M]. |
| Khiva Khanate | Khiva | Khorezm | AI-m | 1 | 1 | [M] |
| Kokand Khanate | Kokand | Fergana | AI-m | 1 | 1 | [M] |
| Kazakh Hordes | none | steppe | Rebel / Russia | 1 | 1 | [H] |

Note: French Pondicherry and Chandernagore (returned 1802, seized again 1803) and Danish Tranquebar/Serampore are too small for regions. Fold them into the Madras and Bengal regions as settlements.

### A.5 East and Southeast Asia

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| Qing: Zhili (Beijing) | Beijing | North China | AI-M (isolationist) | 1 | 1 | Jiaqing Emperor (1796-1820) [H]. White Lotus Rebellion suppressed c.1804 [M]. |
| Qing: Manchuria | Shenyang | Manchu homeland | Qing | 1 | 1 | [H] |
| Qing: Mongolia | Urga | Inner/Outer Mongolia | Qing | 1 | 1 | [H] |
| Qing: Xinjiang | Ili / Urumqi | Dzungaria, Tarim basin | Qing | 1 | 1 | [H] |
| Qing: Tibet | Lhasa | Qing protectorate | Qing | 1 | 1 | [H] |
| Qing: Gansu and Shaanxi | Xi'an | NW China | Qing | 1 | 1 | [H] |
| Qing: Shandong, Henan, Shanxi | Jinan; Kaifeng | North China plain | Qing | 1 | 0 | [H] |
| Qing: Jiangnan | Nanjing; Hangzhou | Yangtze delta | Qing | 1 | 1 | [H] |
| Qing: Canton (Guangdong, Fujian) | Canton (Guangzhou) | S coast, Macau (Portugal) | Qing | 1 | 1 | Canton System, sole trade port [H]. |
| Qing: Sichuan, Hubei, Hunan | Chengdu; Wuhan | middle Yangtze | Qing | 2 | 1 | [H] |
| Qing: Yunnan, Guizhou, Guangxi | Kunming | SW China | Qing | 1 | 1 | [H] |
| Joseon Korea | Hanyang (Seoul) | Korean peninsula | AI-m | 2 | 1 | King Sunjo (1800-34); Sinyu persecution 1801 [M]. |
| Tokugawa Japan: Kanto | Edo | Edo plain | **AI-M** (consider P) | 1 | 1 | Shogun Ienari (1787-1837) [H]. Emperor Kokaku at Kyoto [M]. |
| Tokugawa Japan: Kansai | Kyoto; Osaka | Kinai | Japan | 1 | 1 | [H] |
| Tokugawa Japan: Tohoku | Sendai | N Honshu | Japan | 1 | 1 | [H] |
| Tokugawa Japan: Chugoku and Shikoku | Hiroshima | W Honshu, Shikoku | Japan | 1 | 1 | [H] |
| Tokugawa Japan: Kyushu | Nagasaki; Kagoshima | Kyushu, Dejima | Japan | 1 | 1 | Rezanov embassy at Nagasaki 1804-05 [M]. Phaeton incident 1808 [H]. |
| Tokugawa Japan: Ezo | Matsumae | Hokkaido | Japan | 1 | 0 | [H] |
| Ryukyu | Shuri | islands | Vassal of Satsuma/Qing | 1 | 1 | [H] |
| Dai Viet / Nguyen Vietnam | Hue (Phu Xuan) | Tonkin, Annam, Cochinchina | AI-M | 3 | 2 | Gia Long unifies and takes the throne 1802 [H]. |
| Siam (Rattanakosin) | Bangkok | Siam core + Lan Na and Lao vassals | AI-M | 2 | 1 | Rama I (d.1809) [H]. |
| Burma (Konbaung) | Amarapura | Upper and Lower Burma, Arakan | AI-M | 2 | 1 | Bodawpaya (1782-1819); Arakan conquered 1784 [H]. |
| Cambodia | Oudong | vassal of Siam/Vietnam | Rebel | 1 | 0 | [M] |
| Laos principalities | Vientiane; Luang Prabang | Lao | Siam vassal | 1 | 0 | [H] |
| Malay sultanates | Johor-Riau; Kedah | Malay peninsula | AI-m | 1 | 1 | [M] |
| British Straits (Penang) | George Town | Penang, Bencoolen on Sumatra | Britain colony | 1 | 0 | Penang since 1786 [H]. |
| Aceh and Sumatra | Banda Aceh | N Sumatra | AI-m | 1 | 1 | [H] |
| Dutch East Indies: Java | Batavia | W and central Java | Netherlands | 2 | 1 | Daendels governor 1808 [H]. VOC dissolved 1799 [H]. |
| Vorstenlanden | Surakarta; Yogyakarta | Java princedoms | Dutch vassal | 1 | 0 | [H] |
| Dutch Outer Islands | Ambon; Makassar | Moluccas, Celebes, Padang | Netherlands | 2 | 2 | [H] |
| Borneo and Sulu | Brunei; Banjarmasin | coasts | Rebel | 1 | 1 | [M] |
| Bali, Lombok, Timor | Dili | Portuguese Timor | Rebel/Portugal | 1 | 0 | [M] |
| Spanish Philippines | Manila | Luzon, Visayas | Spain colony | 2 | 1 | Manila galleon to Acapulco runs to 1815 [H]. |

### A.6 Oceania

| Polity / faction | Capital | Rough extent | Role | Full | Lean | Notes and dates |
|---|---|---|---|---|---|---|
| New South Wales | Sydney | Cumberland Plain | Britain colony | 1 | 1 | Founded 1788 [H]. |
| Van Diemen's Land | Hobart | Tasmania | Britain colony | 1 | 0 | Risdon Cove 1803, Hobart 1804 [H]. |
| Aboriginal Australia | none | rest of the continent | Rebel | 2 | 1 | [H] |
| Aotearoa (Maori iwi) | none | North and South Islands | Rebel | 2 | 1 | [H] |
| Kingdom of Hawaii | Kailua; Waikiki (Honolulu later) | Hawaiian islands | AI-m | 1 | 1 | Kamehameha holds all but Kauai/Niihau; Kaumualii becomes tributary 1810, https://www.gohawaii.com/culture/history/king-kamehameha (snippet) [H]. |
| Tahiti (Pomare) | Pare-Arue | Society Islands | AI-m | 1 | 1 | Pomare dynasty, European contact [M]. |
| Tonga, Fiji, Samoa | Mu'a | Western Polynesia | Rebel | 1 | 1 | Tongan civil unrest [L]. |
| Melanesia and Papua | none | New Guinea, Solomons | Rebel | 1 | 0 | Mostly unexplored [H]. |
| Micronesia and Guam | Hagatna | Marianas (Spain) | Spain/Rebel | 1 | 0 | [M] |

### A.7 Europe-side colonial powers: Denmark, Sweden, Netherlands, Portugal, Russia

Already covered above by region. Faction-level notes:

| Power | Overseas holdings to model | Note |
|---|---|---|
| Britain | N America, Caribbean, India (EIC), Ceylon, NSW, Cape (1806), Penang, Gold Coast | Biggest empire. EIC rule means the Indian regions are a sub-faction or mechanic. |
| France | Antilles, Guiana, Senegal, Mascarenes, Louisiana (sold 1803) | Lost Saint-Domingue, so the French colonies are weak. |
| Spain | whole of Latin America, Florida, Philippines | Largest region count. Allied with France; Trafalgar 21 Oct 1805 [H]. |
| Portugal | Brazil, Angola, Mozambique, Goa, Macau, Timor | Court in Lisbon until Nov 1807. |
| Netherlands (Batavian Republic) | Suriname, Curacao, Cape, Java and Indies | Becomes the Kingdom of Holland Jun 1806 [H]. |
| Denmark-Norway | Danish West Indies, Greenland, Iceland, Gold Coast, Tranquebar | Neutral until 1807. |
| Sweden | St-Barthelemy | Negligible. |
| Russia | Alaska, Siberia, Caucasus | Siberia is a very large region count at low density. |
| Ottoman | Anatolia, Levant, Iraq, Hejaz, Egypt (nominal), N Africa (nominal) | Weak central control; many de facto autonomous governors. |

### A.8 Region budget and granularity proposal

Rough tally from the tables above (sum below; verified by script):

| Continent | Full | Lean |
|---|---|---|
| Americas | 61 | 42 |
| Africa | 33 | 24 |
| Middle East | 19 | 15 |
| South and Central Asia | 28 | 21 |
| East and Southeast Asia | 42 | 28 |
| Oceania | 11 | 6 |
| **Non-Europe total** | **194** | **136** |
| Europe (vanilla, about 75-100, **unverified**) | ~80 | ~80 |
| **World total** | **~274** | **~216** |

Recommendations:

1. **Budget:** target the **Lean** profile first (~216 total including Europe), because of the possible ~246 engine ceiling (A.0, **unverified for Napoleon**). Hold the Full counts as the expansion list if testing shows more headroom.
2. **Granularity tiers** (area per region):
   - **Core** (Europe, Mediterranean, Levant): vanilla scale, about 50-150k km².
   - **Interest** (colonial coasts, India, Caribbean, Egypt, Persia, Japan, Qing coast): about 0.2-0.8M km².
   - **Periphery** (Siberia, Sahara/Sahel interior, Amazon, Australia, Central Asia, Arctic): about 1-4M km², one region each, mostly Rebel.
3. **Settlements:** one capital per region; a port only where the coast matters for naval and trade links; towns only in Interest and Core tiers.
4. **Playable set:** keep it small. Vanilla five (France, Britain, Austria, Prussia, Russia) plus candidates Ottoman, Spain, USA, Netherlands, a Maratha or Persia faction. Only add factions that have a working army-and-campaign gameplay loop. Qing and Japan are better as AI-only isolationist powers.
5. **Rebel/minor taxonomy:** (1) AI-M major; (2) AI-m minor with its own diplomacy; (3) subsidiary or vassal (Awadh, Hyderabad, Mysore); (4) Rebel/Neutral, a no-diplomacy native hold-out. "Emerging" factions map well to Haiti, Sokoto, Latin American republics (1810+), Greek, Serbian.
6. **Sea regions:** Empire used 4 sea-only trade theatres (A.0). Plan about 20-30 sea zones (North Atlantic, Caribbean, South Atlantic, Cape route, Indian Ocean west/east, Bay of Bengal, South China Sea, Pacific, and similar).

### A.9 Notable-date timeline (1801-1810)

| Date | Event | Conf. |
|---|---|---|
| 1801 | Georgia annexed by Russia (Sept) | H |
| 1801 | Ranjit Singh proclaimed Maharaja (took Lahore 1799) | H-M |
| 1802 | Treaty of Amiens, Britain keeps Ceylon and Trinidad | H |
| 1802 | Gia Long takes the throne, Nguyen Vietnam | H |
| Dec 1802 | Treaty of Bassein | H |
| 1803 | Louisiana Purchase (30 Apr treaty, 20 Dec transfer) | H |
| 1803 | Second Anglo-Maratha War begins, Delhi taken (Sept), Assaye (Sept) | H |
| 1803 | Wahhabis take Mecca; Medina 1805 | M-H |
| 1803 | British seize Demerara, Essequibo, Berbice | M |
| 1803 | Van Diemen's Land first settlement | H |
| 1 Jan 1804 | Haitian independence; Dessalines emperor Oct 1804 | H |
| Feb 1804 | Usman dan Fodio's jihad, Sokoto Caliphate | H |
| 1804 | Serbian uprising (Feb); Russo-Persian War begins; Sitka (Oct) | H |
| 1804 | Napoleon crowned Emperor (Dec) | H |
| 1804-05 | Rezanov at Nagasaki | M |
| Jun 1805 | First Barbary War ends | H |
| 1805 | Muhammad Ali becomes wali of Egypt | M |
| 21 Oct 1805 | Trafalgar | H |
| 2 Dec 1805 | Austerlitz | H |
| 24 Dec 1805 | Treaty of Rajghat (Holkar) | M |
| Jan 1806 | British take Cape at Blaauwberg | H |
| 1806 | Dissolution of the Holy Roman Empire; Kingdom of Holland (Jun) | H |
| 1806-07 | British invasions of Buenos Aires | H |
| 1807 | British slave-trade abolition; Portuguese court to Brazil (Nov) | H |
| 1808 | Peninsular War, Spanish juntas; Gobir falls to Sokoto | H |
| 1810 | Kauai joins Hawaii; Mexican Grito (Sept) | H |

---

## B. Open geodata sources

All "licence" cells say whether they were **confirmed in search snippets** or **[unverified-web]**. For games shipped to others, the licence of every derived asset (baked map textures included) matters. Read the actual licence text before shipping.

### B.1 Elevation and bathymetry

| Dataset | Content | Resolution | Licence | URL | Format |
|---|---|---|---|---|---|
| GEBCO_2025 grid (a GEBCO_2026 grid was published 23 Apr 2026, check the newest) | global land elevation + ocean bathymetry | 15 arc-sec (~450 m); single 7.5 GB file | Public domain, free incl. commercial, **attribution required**; not for navigation; do not imply GEBCO endorsement (confirmed) | https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2025-grid ; terms https://www.gebco.net/data-products/gridded-bathymetry/terms-of-use ; download https://download.gebco.net | netCDF-4 (global); GeoTIFF/ASCII for subsets |
| ETOPO 2022 | global relief, "Ice Surface" and "Bedrock" versions | 15, 30, 60 arc-sec; 15" in 15x15 degree tiles, 30"/60" global files | **US federal data; formal licence not shown in snippets**, check the DOI page ([unverified-web]: normally public domain). Cite DOI 10.25921/fd45-gt74 | https://www.ncei.noaa.gov/products/etopo-global-relief-model | GeoTIFF, netCDF |
| SRTM GL1 v3 | land only, void-filled with ASTER GDEM2, GMTED2010, NED | 1 arc-sec (~30 m), 60N to 56S | NASA open data, **licence text not confirmed in snippets** [unverified-web: free, unrestricted] | https://www.earthdata.nasa.gov/data/catalog/lpcloud-srtmgl1-003 | HGT / GeoTIFF 1x1 degree tiles |
| Copernicus DEM GLO-90 / GLO-30 | global surface model (includes buildings and canopy), **no ocean tiles** (assume 0) | 90 m / 30 m; some GLO-30 tiles withheld for two countries | Free under the Copernicus licence (confirmed) | https://registry.opendata.aws/copernicus-dem/ | Cloud-optimized GeoTIFF, S3 `copernicus-dem-30m` (eu-central-1), anonymous |
| Natural Earth shaded relief + bathymetry | cartographic rasters and depth polygons | 1:10m, 1:50m, 1:110m | Public domain (confirmed) | https://www.naturalearthdata.com/downloads/10m-physical-vectors/ | GeoTIFF, shapefile |

**Recommendation for a world map at ~2.5-5 km/pixel:** do not use 30 m data. Use **ETOPO 2022 60 arc-sec bedrock** or **GEBCO 15" averaged down**. Both are small enough to resample whole in one pass. SRTM or Copernicus is only worthwhile for local detail zooms such as a battle map. Use the **bedrock** ETOPO variant so Greenland and Antarctica are rock, not ice (ice-surface heights misrepresent coastline and basin shape).

### B.2 Coastlines and modern admin borders

| Dataset | Content | Resolution | Licence | URL | Format |
|---|---|---|---|---|---|
| Natural Earth vector | coastline, land, countries, admin-1 states/provinces, lakes, rivers, ports, populated places, geography regions | 1:10m / 50m / 110m | **Public domain, no attribution needed** (confirmed) | https://www.naturalearthdata.com/downloads/ ; mirror https://github.com/nvkelso/natural-earth-vector | shapefile, GeoJSON |
| Natural Earth layers to pull | `ne_10m_land`, `ne_10m_coastline`, `ne_10m_admin_0_countries`, `ne_10m_admin_1_states_provinces`, `ne_10m_lakes`, `ne_10m_rivers_lake_centerlines`, `ne_10m_populated_places`, `ne_10m_ports`, `ne_10m_geography_regions_polys` | 1:10m | as above | as above | **layer names from memory [unverified-web]** |

Note: Natural Earth countries are **modern borders** (and contain disputed-area political choices). Use them for coastline and as a spatial skeleton for assigning regions (for example admin-1 units as region building blocks), not as 1805 political borders.

### B.3 Historical borders around 1800

| Dataset | Content | Resolution / years | Licence | URL | Format |
|---|---|---|---|---|---|
| aourednik/historical-basemaps | georeferenced world polygons per snapshot year | Many years. **Confirmed present: world_1783, world_1800, world_1815** (1880 not confirmed). An auto-generated `index.json` lists every year and file. | **GPL-3.0** per repo page (confirmed). **Open issue #74 (Jun 2026) asks whether GPL-3.0 was meant to cover the data**; unresolved ambiguity. README says work in progress, verify before academic use. | https://github.com/aourednik/historical-basemaps ; file https://github.com/aourednik/historical-basemaps/blob/master/geojson/world_1800.geojson | GeoJSON |
| HistoryLayer-borders (fork) | TopoJSON-simplified fork of the above | same snapshots | GPL-3.0 (stated by the fork) | https://github.com/NovarkWorks/HistoryLayer-borders | TopoJSON |
| idris-maps/world-historical-gis-data | "2000 BCE to 1994 CE" | multiple years | **not checked** | https://github.com/idris-maps/world-historical-gis-data | GeoJSON |
| Euratlas "Georeferenced Historical Vector Data 1800" | **Europe and Mediterranean only**, high detail | century-end snapshots, 1800 available | **Commercial**: simple (non-commercial) licence 150 EUR, extended (commercial) 600 EUR per snapshot page (prices from a possibly old page, check) | https://euratlas.com/shop/1_gis_1800.html ; info https://euratlas.net/history/europe/gis.html | shapefile |
| CShapes 2.0 | country borders **1886-2019 only** | annual | **Unclear**: CC BY-NC article record; a third party says CC BY-NC-SA 4.0; non-commercial looks likely, **verify with authors** | https://icr.ethz.ch/data/cshapes/ (unverified path); R package https://rdrr.io/cran/cshapes | shapefile |

Assessment:
- **aourednik** is the only free, whole-world, ~1800 snapshot found, but expect coarse polygons, with approximate borders in Africa, interior Americas, Central Asia, and Siberia. Field names (`NAME`, `SUBJECTO`, `PARTOF`, `BORDERPRECISION`) are from memory **[unverified-web]**, so inspect the file. Use it as a **seed** to be edited by hand into game regions, not as final geometry.
- **GPL-3.0 and a mod:** a GPL derived work may force the map data to ship under GPL. If the mod is non-commercial and open data is acceptable, this is probably fine. Otherwise **draw the borders ourselves** using aourednik as a visual reference only. **Check with the user.**
- **Euratlas** is paid and Europe-only. Vanilla Napoleon already covers Europe, so skip it.
- **CShapes** starts 81 years after 1805. It is of little use here beyond a sanity check on stable coastlines or late-19th-century outlines.
- Other visual references (georeferencing aids, not data): David Rumsey Map Collection https://www.davidrumsey.com (licensing varies per map, **[unverified-web]**).

### B.4 Rivers and hydrography

| Dataset | Content | Resolution | Licence | URL | Format |
|---|---|---|---|---|---|
| Natural Earth `rivers_lake_centerlines` | single-line cartographic rivers with width attribute; no intermittent rivers; suspect alignment in NE Russia and parts of the Amazon | 1:10m, 1:50m | Public domain (confirmed) | https://www.naturalearthdata.com/downloads/10m-physical-vectors/ | shapefile |
| HydroRIVERS | vector network of all rivers with catchment at least 10 km2 or flow at least 0.1 m3/s; lower quality north of 60 N | derived from 15" HydroSHEDS | HydroSHEDS licence agreement: free for non-commercial **and** commercial use, with conditions (confirmed from catalogue snippets; full text not read). Cite Lehner and Grill 2013, Hydrol. Process. 27(15) | https://www.hydrosheds.org/products/hydrorivers | geodatabase, shapefile (WGS84) |
| HydroSHEDS basins (HydroBASINS) | nested watersheds (levels 1-12) | 15" | same HydroSHEDS licence | https://www.hydrosheds.org | shapefile |

**Recommendation:** use Natural Earth rivers for the visible rendering layer (small, cleaned). Use HydroRIVERS filtered by discharge (attribute `DIS_AV_CMS`, from memory **[unverified-web]**) only if you need a precise drainage graph (river crossings, movement costs, region adjacency along rivers). Unfiltered HydroRIVERS is millions of segments. Note modern dams, canals, and the Aral Sea shrinkage make some modern hydrography anachronistic. Lake Chad and the Aral Sea were larger in 1805.

### B.5 Climate, land cover, biomes (for terrain and climate assignment)

| Dataset | Content | Resolution | Licence | URL | Format |
|---|---|---|---|---|---|
| Beck et al. 2018 Koppen-Geiger | present (1980-2016) and future (2071-2100) Koppen classes; legend file | 1 km | **CC BY 4.0 [unverified-web]**: not shown in snippets, check the figshare licence field | https://figshare.com/articles/dataset/Present_and_future_K_ppen-Geiger_climate_classification_maps_at_1-km_resolution/6396959 ; http://www.gloh2o.org/koppen ; paper https://pmc.ncbi.nlm.nih.gov/articles/PMC6207062 | GeoTIFF, uint8 |
| ESA WorldCover 2021 v200 | 11-class land cover (also 2020 v100) | 10 m; 3x3 degree tiles; full map ~120 GB | **CC BY 4.0** (confirmed) | https://worldcover2021.esa.int/download ; AWS `s3://esa-worldcover` (eu-central-1, anonymous) https://registry.opendata.aws/esa-worldcover-vito/ | Cloud-optimized GeoTIFF |
| RESOLVE Ecoregions 2017 (Dinerstein et al.) | 846 terrestrial ecoregions, 14 biomes, 8 realms | vector | **CC BY 4.0** (confirmed via GEE catalog) | https://developers.google.com/earth-engine/datasets/catalog/RESOLVE_ECOREGIONS_2017 ; http://ecoregions.appspot.com | shapefile / GeoJSON |
| WWF Terrestrial Ecoregions (Olson et al. 2001) | 867 ecoregions, 14 biomes | vector | **not confirmed** | https://www.worldwildlife.org/publications/terrestrial-ecoregions-of-the-world | shapefile |
| HYDE 3.3 | population, urban/rural, cropland (rainfed and irrigated, rice), grazing, built-up area for 10,000 BCE-2023 CE, so **1800 is available** | 5 arc-min (~10 km) | Utrecht Univ open repository ("Open - freely retrievable"). **Exact licence not shown in snippets**, check the DOI landing page ([unverified-web]: CC BY 4.0) | https://public.yoda.uu.nl/geo/UU01/AEZZIT.html ; catalogue https://catalog.data.uu.nl/dataset/oai-10-24416-uu01-67uhb4 | ESRI ASCII grid |

**Anachronism warning:** Koppen and WorldCover describe the **modern** world (1980-2016, 2021). WorldCover's cropland, built-up, and many forest/pasture classes are post-1805 artefacts (for example North American prairie farmland, Amazon deforestation, Sahel/Aral changes). For 1805 use them only for **natural** classes (desert, ice, tundra, mangrove, natural forest) and reclassify farmland through **HYDE 1800 cropland/grazing**. The 1790-1830 Dalton Minimum and the tail of the Little Ice Age (**[unverified-web]**, general climate history) mean a colder baseline than the 1980-2016 Koppen map, so treat Koppen as a palette seed. Ecoregions (RESOLVE/WWF) are a "potential natural vegetation" product and fit an 1805 map better.

### B.6 Historical cities, population, trade

| Dataset | Content | Resolution | Licence | URL | Format |
|---|---|---|---|---|---|
| Reba, Reitsma, Seto 2016, "Spatializing 6,000 years of global urbanization" | geocoded historical city populations (digitised from Chandler 1987 and Modelski 2003); fields: city, lat, lon, year, population, reliability rank. Includes the ~1800 slice. | city points | **not confirmed in snippets** (hosted on NASA SEDAC / data.nasa.gov; check record) | paper https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4896125/ ; data https://data.nasa.gov/dataset/historical-urban-population-3700-bc-ad-2000 | CSV (DOI 10.1038/sdata.2016.34) |
| HYDE 3.3 (above) | gridded population density 1800 | 5 arc-min | see B.5 | see B.5 | ASCII grid |
| CLIWOC | ~287,000 ship logbook records (Dutch, British, French, Spanish) 1750-1854 with positions and weather; Pacific coverage poor; original release is Microsoft Access | positions per log entry | **not checked** | https://en.wikipedia.org/wiki/CLIWOC ; paper https://link.springer.com/article/10.1007/s10584-005-6952-6 ; LoC interactive map https://blogs.loc.gov/maps/2023/04/new-interactive-map-visualizes-ship-logbooks-from-the-18th-and-19th-centuries/ | Access database / CSV |
| Natural Earth ports + populated places | modern port and city points | 1:10m | public domain | see B.2 | shapefile |

**Trade routes:** **I did not find a ready-made open GIS dataset of 1800 shipping or caravan routes.** Plan to author about 40-60 routes by hand, informed by CLIWOC position density for sea lanes, and the known main routes: the Cape route (Europe-India-Canton), the Atlantic triangle, the Manila galleon (Acapulco-Manila), the Spice Islands route, Mediterranean-Levant, and the main caravan routes (Trans-Saharan, Silk Road, Hajj). Use Reba et al. and HYDE as the sanity check for which cities rate a port or major settlement. Ports: pick from Natural Earth ports filtered to those with a pre-1805 city in Reba et al., plus manual additions (Canton, Macau, Dejima, Batavia).

### B.7 Suggested pipeline

1. Coastline and land mask: Natural Earth 10m `land` and `lakes`, with manual fixes for 1805 (Aral Sea, Lake Chad level).
2. Heightmap: ETOPO 2022 60" bedrock (or GEBCO 15" resampled), reprojected to the game projection (section C).
3. Borders: seed from `world_1800.geojson` (aourednik, mind the GPL point), cut to Natural Earth coastline, then hand-edit into the region list of Section A. Region boundaries should follow modern admin-1 units where they roughly match.
4. Rivers: Natural Earth rivers for rendering; HydroRIVERS (filtered) for adjacency and crossing costs.
5. Terrain/climate class per pixel: RESOLVE ecoregions biome + Koppen (natural classes) + HYDE 1800 cropland for farmland.
6. Settlements: Reba et al. 1800 city points to place capitals and towns; Natural Earth ports for the port list.
7. Keep every raw download untouched in its own directory; write derived assets to a separate output directory.

---

## C. Projection notes

### C.1 Recommendation

- **Author in geographic coordinates (EPSG:4326, plate carree) and bake the game map in the Miller cylindrical projection.** Every source above is delivered in 4326, so one reprojection step is enough.
- PROJ definition: `+proj=mill +R=6371007.2 +lon_0=10.5 +x_0=0 +y_0=0` (sphere; `+lon_0` is the seam choice, see C.3).
- Miller formula: `x = R * (lambda - lambda0)`, `y = 1.25 * R * ln(tan(pi/4 + 0.4 * phi))` (confirmed, https://en.wikipedia.org/wiki/Miller_cylindrical_projection ; https://proj4.org/en/stable/operations/projections/mill.html). Inverse: `phi = 2.5 * atan(exp(0.8 * y / R)) - 0.625 * pi`.
- Miller is rectangular, so it keeps the orthogonal grid that a tile or region-paint workflow expects. It is a Mercator compromise that does **not** send the poles to infinity (confirmed; the sources note that distortion is still severe at the poles).

### C.2 Distortion comparison (scale factors; computed here, not from a source)

For Miller, east-west scale k = sec(phi) and north-south scale h = sec(0.8 phi). Area scale = h x k. Shape squeeze ratio = k / h (1.0 means undistorted shape).

| Latitude | Equirect area | Miller area | Mercator area | Equirect shape ratio (E-W vs N-S) | Miller shape ratio |
|---|---|---|---|---|---|
| 0 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 30 | 1.15 | 1.26 | 1.33 | 1.15 | 1.06 |
| 50 | 1.56 | 2.03 | 2.42 | 1.56 | 1.19 |
| 60 | 2.00 | 2.99 | 4.00 | 2.00 | 1.34 |
| 70 | 2.92 | 5.23 | 8.55 | 2.92 | 1.64 |

(For equirect "shape ratio" read: east-west lengths are drawn too long by this factor at that latitude relative to north-south.)

Reading: Europe (35-70N) sits where equirect smears shapes (about 1.2-2.9x). Miller keeps shapes much closer to true (about 1.1-1.6x) at the cost of inflating area (about 1.5-5x). Europe is where the vanilla game already sits, so it should look familiar. Equirect also makes Europe look flat and wide; Mercator is conformal but inflates Russia and Canada hardest.

### C.3 Edges, seam, poles

- **No wraparound.** Total War campaign maps are flat with hard edges, so choose a seam and treat it as the map edge. **Recommended seam about 169.5W** (set `+lon_0=10.5`, giving a window of -169.5 to +190.5). This passes through open Pacific, between Chukotka's tip (Cape Dezhnev at about 169.7W, **from memory**, check against Natural Earth) and the Aleutians/Alaska, and keeps Eurasia, Africa, the Americas, Hawaii, Fiji, Tonga, Samoa, and New Zealand all on one side unbroken. **Verify against `ne_10m_land` that no polygon is cut** before locking `lon_0`.
- **Latitude window:** clip at about **+80 N and -58 S** (covers Cape Horn at 56S and Arctic Siberia and Greenland coasts; Antarctica was not discovered until 1820). Miller y values: y(+80) = 1.832 R, y(-58) = -1.145 R, so height = 2.977 R against width 2 pi R = 6.283 R, an aspect of **about 2.11 : 1** (computed here).
- **Resolution examples:** at 16384 x 7766 px, 1 px = 2.45 km east-west at the equator (40,075 km / 16384). East-west km per px at latitude phi is 2.45 cos(phi) (about 1.6 km at 50N). North-south km per px is 2.45 cos(0.8 phi) (about 1.9 km at 50N). At 8192 px width everything doubles.
- **Pacific crossings:** the Manila galleon (Acapulco-Manila) crosses the seam. Model it as a **paired sea-link teleport** across the map edge or abstract it as a trade link between the Philippines and New Spain.
- **Polar:** nothing playable is north of about 75N (Taymyr, Greenland west coast, Svalbard unsettled). A hard ice-edge border is fine. For heightmaps, clamp values above 80N rather than extrapolating.

### C.4 Do not use Robinson (or other pseudocylindricals) as the game space

Robinson and similar pseudocylindrical projections have curved meridians and a non-rectangular outline. They look good in print but break rectangular tile and region-paint workflows, camera panning, and axis-aligned collision, and the clipped corners waste texture. If wanted for a **UI minimap or overview art**, render that separately from the same 4326 data.

### C.5 Gameplay consequences

- **Movement and distances:** screen distance is not ground distance in Miller. Compute movement cost and supply range on the sphere (haversine, or per-pixel local scale k = sec(phi)), or armies will move too slowly relative to the real world at high latitudes and the Arctic will look huge. Alternatively accept a flat per-pixel cost for the whole map, as vanilla does for Europe.
- **Vanilla Europe:** the vanilla Napoleon Europe map is likely hand-drawn, not geographically exact, so register it to the Miller base with ground control points (a thin-plate-spline warp of roughly 30 points is the obvious route; a design suggestion, not a verified method). Alternatively keep vanilla Europe as is and attach a Miller-projected remainder around it.
- **Heightmap shading:** elevation values are heights, not distorted, but slope looks shallower at high latitudes (horizontal stretch k). Scale the vertical exaggeration by local k when computing normals or hillshade, or terrain at 60N looks flatter than at the equator.
- **Great circles:** sea routes drawn as straight Miller lines are rhumb-like. For long routes (Cape route, Pacific) add waypoints at known 1805 sailing tracks rather than trusting straight lines.

---

## D. Open questions and risks

1. **True engine region cap** for Napoleon (~246 inferred for Empire from one old forum post). Count the NTW startpos and test-add regions. This determines Full vs Lean.
2. **GPL-3.0 on aourednik data**: whether it propagates to the mod. Needs a user decision (hand-draw borders vs reuse).
3. **Licences not confirmed** in this session: ETOPO 2022, SRTM, Koppen (figshare), HYDE 3.3, Reba et al., WWF/Olson, CLIWOC, CShapes. Read each licence page before shipping any derived asset.
4. **WebFetch was blocked**, so no page was read in full. All "confirmed" labels mean "appeared in a search snippet from the named URL".
5. Historical tags [M]/[L] (Muhammad Ali's 1805 date, Oyo timing, Tonga politics, exact Afghan rulers, Hawaii capital) need a second source before they go into faction scripts.
6. Anachronistic data (Koppen, WorldCover, modern hydrography, modern borders) must be corrected by hand for 1805 (Section B.5).
