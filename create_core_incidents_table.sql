-- SQL Query to create core_incidents table for Capture application
-- Run this query in your MySQL database: resilience_tenent

CREATE TABLE IF NOT EXISTS `core_incidents` (
    `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL COMMENT 'Update Title / Incident Title',
    `description` LONGTEXT NOT NULL COMMENT 'What Changed? / Description',
    `severity` VARCHAR(10) NOT NULL COMMENT 'Severity level: LOW, MEDIUM, HIGH, CRITICAL',
    `impact` LONGTEXT NOT NULL COMMENT 'Why it Matters (Impact)',
    `next_action` VARCHAR(255) NOT NULL COMMENT 'Next Action to be taken',
    `start_time` DATETIME NULL COMMENT 'Start Time of the incident',
    `end_time` DATETIME NULL COMMENT 'End Time of the incident',
    `timestamp` DATETIME(6) NOT NULL COMMENT 'When the record was created',
    `is_synthesized` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Whether this is a synthesized update',
    `owner_id` BIGINT NULL COMMENT 'Foreign key to core_liaison table',
    `organization_id` BIGINT NOT NULL COMMENT 'Foreign key to core_organization table',
    INDEX `idx_organization_id` (`organization_id`),
    INDEX `idx_owner_id` (`owner_id`),
    INDEX `idx_timestamp` (`timestamp`),
    INDEX `idx_severity` (`severity`),
    INDEX `idx_start_time` (`start_time`),
    CONSTRAINT `fk_incidents_organization` 
        FOREIGN KEY (`organization_id`) 
        REFERENCES `core_organization` (`id`) 
        ON DELETE CASCADE,
    CONSTRAINT `fk_incidents_owner` 
        FOREIGN KEY (`owner_id`) 
        REFERENCES `core_liaison` (`id`) 
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
