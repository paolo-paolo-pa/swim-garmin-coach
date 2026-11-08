-- Una colonna che si chiama «secondi» contiene secondi.
--
-- Le sei colonne `hr_zone_0_s` … `hr_zone_5_s` contenevano **millisecondi**.
-- Garmin espone `hrTimeInZone_N` in millisecondi come tutte le altre durate, e
-- l'importatore le leggeva con `units.value` invece che con `units.seconds`,
-- che divide per mille. Le altre durate della stessa riga — `duration_s`,
-- `moving_duration_s` — erano lette correttamente: è stata una svista su sei
-- campi vicini, non una scelta.
--
-- ## Come è venuta fuori
--
-- Sommando le sei zone di una seduta e confrontandole con la sua durata:
--
--     03/07/2026   durata 3.559 s   somma zone 3.532.837   rapporto 992,6
--     01/07/2026   durata 4.661 s   somma zone 4.619.682   rapporto 991,1
--
-- Il rapporto è mille, meno il tempo in cui l'orologio non ha letto la
-- frequenza. Non è un'ipotesi: è la stessa costante su ogni seduta.
--
-- ## Perché non se n'era accorto nessuno
--
-- Perché **nessuna analisi leggeva quelle colonne.** Sono entrate in archivio
-- con la Fase 1 e sono rimaste lì, esatte nella forma e sbagliate di tre ordini
-- di grandezza, per tutto il tempo in cui il coach ha ragionato sul passo e non
-- sulla frequenza cardiaca. Il primo che le avesse usate avrebbe detto
-- all'atleta che ha passato novantatré ore in zona 3 in una seduta.
--
-- È il tipo di guasto che questo progetto teme di più: non rompe niente,
-- aspetta. Da qui il criterio C16, che confronta la somma delle zone con la
-- durata e fallisce se le due non stanno insieme.
--
-- ## Perché una migrazione e non solo la correzione dell'importatore
--
-- Perché le righe già in archivio non si riscrivono da sole. `ingest` è
-- idempotente e riscrive tutto dall'export, ma un database che non venga
-- reimportato resterebbe con i valori vecchi e nessun segno: è esattamente il
-- caso descritto in `schema_migrations.py`, la colonna aggiunta oggi che non
-- comparirà mai in un database creato ieri.
--
-- La conversione è sicura perché è idempotente rispetto al criterio: dopo,
-- C16 passa; se venisse applicata due volte, C16 fallirebbe subito con la
-- somma a un millesimo della durata.

UPDATE activities
   SET hr_zone_0_s = hr_zone_0_s / 1000.0,
       hr_zone_1_s = hr_zone_1_s / 1000.0,
       hr_zone_2_s = hr_zone_2_s / 1000.0,
       hr_zone_3_s = hr_zone_3_s / 1000.0,
       hr_zone_4_s = hr_zone_4_s / 1000.0,
       hr_zone_5_s = hr_zone_5_s / 1000.0
 WHERE coalesce(hr_zone_0_s, 0) + coalesce(hr_zone_1_s, 0)
     + coalesce(hr_zone_2_s, 0) + coalesce(hr_zone_3_s, 0)
     + coalesce(hr_zone_4_s, 0) + coalesce(hr_zone_5_s, 0)
     > duration_s * 100;
