// Compatibility shim. The Dashboard tab consolidated "Overview" and
// "Merchant" into one view (MerchantDashboard). This file keeps the
// legacy named export so any remaining importer keeps working.
export { MerchantDashboard as OverviewView } from './MerchantDashboard';