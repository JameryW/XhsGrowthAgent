import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge Tailwind classes with clsx for cleaner component code
 * Handles class conflicts properly (e.g., p-4 + p-2 = p-2)
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}