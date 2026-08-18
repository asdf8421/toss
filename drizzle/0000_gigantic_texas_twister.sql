CREATE TABLE `analysis_snapshots` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`run_id` text NOT NULL,
	`as_of_date` text NOT NULL,
	`published_at` text NOT NULL,
	`payload_json` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_snapshots_run_id_unique` ON `analysis_snapshots` (`run_id`);--> statement-breakpoint
CREATE INDEX `idx_analysis_snapshots_published_at` ON `analysis_snapshots` (`published_at`);