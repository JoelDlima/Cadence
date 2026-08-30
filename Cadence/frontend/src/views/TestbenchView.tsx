// Compatibility shim. The Test Lab tab consolidated "Results" and
// "Simulation & Chaos" into a single view (TestLabView). This file
// keeps the legacy named export so any remaining importer keeps working.
export { default as TestbenchView } from './TestLabView';
export { default } from './TestLabView';