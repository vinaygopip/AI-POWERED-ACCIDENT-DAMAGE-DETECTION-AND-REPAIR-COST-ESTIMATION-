import config
from database import get_db_connection

DEFAULT_PART_PRICES = {
    'Bonnet': 15000,
    'Bumper': 10000,
    'Dickey': 8000,
    'Door': 20000,
    'Fender': 5000,
    'Light': 3000,
    'Windshield': 8000
}

SEVERITY_LABOUR_HOURS = {
    'Minor': {'hours': 2, 'labour_multiplier': 1.0, 'paint_multiplier': 0.8},
    'Moderate': {'hours': 4, 'labour_multiplier': 1.5, 'paint_multiplier': 1.2},
    'Severe': {'hours': 8, 'labour_multiplier': 2.5, 'paint_multiplier': 1.8}
}

class CostEstimator:
    def __init__(self):
        pass

    def calculate_repair_cost(self, car_brand, model_name, detections):
        """
        Module 5: Cost Estimation Logic
        - Parts Cost
        - Labour Cost
        - Paint Cost
        - Repair Time (Hours & Days)
        - Total Estimated Cost (with tax)
        """
        conn = get_db_connection()
        itemized_breakdown = []
        total_parts_cost = 0.0
        total_labour_cost = 0.0
        total_paint_cost = 0.0
        total_repair_hours = 0

        for det in detections:
            part_name = det.get('part_name', 'Bumper')
            severity = det.get('severity', 'Moderate')
            damage_type = det.get('damage_type', 'Dent')

            # 1. Fetch Part Price from DB
            part_price = self._lookup_part_price(conn, car_brand, model_name, part_name)
            
            # Adjust part cost if damage is minor (repair vs complete replace)
            if severity == 'Minor' and damage_type in ['Scratch', 'Dent']:
                effective_part_cost = part_price * 0.3  # Repair cost instead of full replacement
            elif severity == 'Moderate':
                effective_part_cost = part_price * 0.7
            else:
                effective_part_cost = part_price * 1.0  # Full replacement needed

            # 2. Calculate Labour & Paint Costs
            sev_info = SEVERITY_LABOUR_HOURS.get(severity, SEVERITY_LABOUR_HOURS['Moderate'])
            hours = sev_info['hours']
            labour_cost = hours * config.LABOUR_RATE_PER_HOUR * sev_info['labour_multiplier']
            paint_cost = config.BASE_PAINT_COST_PER_PART * sev_info['paint_multiplier']

            total_parts_cost += effective_part_cost
            total_labour_cost += labour_cost
            total_paint_cost += paint_cost
            total_repair_hours += hours

            itemized_breakdown.append({
                'part_name': part_name,
                'damage_type': damage_type,
                'severity': severity,
                'base_part_price': round(part_price, 2),
                'effective_part_cost': round(effective_part_cost, 2),
                'labour_hours': hours,
                'labour_cost': round(labour_cost, 2),
                'paint_cost': round(paint_cost, 2),
                'item_total': round(effective_part_cost + labour_cost + paint_cost, 2)
            })

        if conn:
            try:
                conn.close()
            except Exception:
                pass

        subtotal = total_parts_cost + total_labour_cost + total_paint_cost
        tax_amount = subtotal * (config.TAX_RATE_PERCENTAGE / 100.0)
        total_estimated_cost = subtotal + tax_amount
        estimated_days = max(1, round(total_repair_hours / 6.0, 1))

        return {
            'itemized_breakdown': itemized_breakdown,
            'summary': {
                'total_parts_cost': round(total_parts_cost, 2),
                'total_labour_cost': round(total_labour_cost, 2),
                'total_paint_cost': round(total_paint_cost, 2),
                'subtotal': round(subtotal, 2),
                'tax_rate': config.TAX_RATE_PERCENTAGE,
                'tax_amount': round(tax_amount, 2),
                'total_estimated_cost': round(total_estimated_cost, 2),
                'total_repair_hours': total_repair_hours,
                'estimated_days': estimated_days
            }
        }

    def _lookup_part_price(self, conn, brand, model, part):
        if not conn:
            return DEFAULT_PART_PRICES.get(part, 5000)

        try:
            with conn.cursor(dictionary=True) as cursor:
                # 1. Exact match brand & model
                cursor.execute(
                    "SELECT price FROM car_models WHERE LOWER(brand) = LOWER(%s) AND LOWER(model) = LOWER(%s) AND LOWER(part) = LOWER(%s)",
                    (brand, model, part)
                )
                res = cursor.fetchone()
                if res and 'price' in res:
                    return float(res['price'])

                # 2. Match brand
                cursor.execute(
                    "SELECT price FROM car_models WHERE LOWER(brand) = LOWER(%s) AND LOWER(part) = LOWER(%s)",
                    (brand, part)
                )
                res = cursor.fetchone()
                if res and 'price' in res:
                    return float(res['price'])
        except Exception as e:
            print(f"Error querying part price in DB: {e}")

        return DEFAULT_PART_PRICES.get(part, 6000)
