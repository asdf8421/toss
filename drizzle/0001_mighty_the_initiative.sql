CREATE TABLE `analysis_requests` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`request_id` text NOT NULL,
	`status` text NOT NULL,
	`requested_at` text NOT NULL,
	`previous_run_id` text,
	`completed_at` text,
	`completed_run_id` text,
	`failure_message` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_requests_request_id_unique` ON `analysis_requests` (`request_id`);--> statement-breakpoint
CREATE INDEX `idx_analysis_requests_requested_at` ON `analysis_requests` (`requested_at`);--> statement-breakpoint
PRAGMA optimize;
