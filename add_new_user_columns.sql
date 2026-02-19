-- SQL Query to add new columns to the users table
-- Run these queries in your MySQL database: resilience_tenent

USE resilience_tenent;

-- Add Name column
ALTER TABLE users 
ADD COLUMN name VARCHAR(150) NULL AFTER id;

-- Add Mobile No column
ALTER TABLE users 
ADD COLUMN mobile_no VARCHAR(20) NULL AFTER name;

-- Add Email ID column
ALTER TABLE users 
ADD COLUMN email_id VARCHAR(150) NULL AFTER mobile_no;

-- Add Department column
ALTER TABLE users 
ADD COLUMN department VARCHAR(200) NULL AFTER email_id;

-- Add Sub Department column
ALTER TABLE users 
ADD COLUMN sub_department VARCHAR(200) NULL AFTER department;

-- Add Shift Start Time column
ALTER TABLE users 
ADD COLUMN shift_start_time TIME NULL AFTER sub_department;

-- Verify the columns were added
DESCRIBE users;
