ALTER TABLE `analysis_requests` ADD `market_scope` text DEFAULT 'KR' NOT NULL;--> statement-breakpoint
CREATE INDEX `idx_analysis_requests_market_requested` ON `analysis_requests` (`market_scope`,`requested_at`);--> statement-breakpoint
ALTER TABLE `analysis_snapshots` ADD `market_scope` text DEFAULT 'KR' NOT NULL;--> statement-breakpoint
CREATE INDEX `idx_analysis_snapshots_market_published` ON `analysis_snapshots` (`market_scope`,`published_at`);