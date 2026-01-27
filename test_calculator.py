#!/usr/bin/env python3
"""Test script to verify the customs calculator logic"""

from bot import CustomsCalculator

def test_calculator():
    calculator = CustomsCalculator()
    
    print("Тестирование калькулятора таможенных пошлин...")
    print("="*50)
    
    # Test case 1: Car 1-3 years old
    print("\nТест 1: Автомобиль возрастом 2 года")
    result1 = calculator.calculate_customs(
        purchase_price=20000,
        currency='USD',
        manufacture_date='2024-01-01',
        engine_volume=2.0,
        hp=150,
        importer_type='Физическое лицо'
    )
    print(f"Стоимость: {result1['purchase_price']} {result1['currency']}")
    print(f"Возраст: {result1['vehicle_age']} лет")
    print(f"Объем двигателя: {result1['engine_volume']}L")
    print(f"Лошадиных сил: {result1['horsepower']} HP")
    print(f"Тип импортера: {result1['importer_type']}")
    print(f"Таможенная пошлина: {result1['customs_duty']:,} RUB")
    print(f"Утилизационный сбор: {result1['recycling_fee']:,} RUB")
    print(f"Всего к оплате: {result1['total_payable']:,} RUB")
    
    # Test case 2: Car 3-5 years old with low horsepower
    print("\nТест 2: Автомобиль возрастом 4 года, до 160 л.с.")
    result2 = calculator.calculate_customs(
        purchase_price=15000,
        currency='EUR',  # Will use default rate of 1
        manufacture_date='2021-01-01',
        engine_volume=1.8,
        hp=140,
        importer_type='Физическое лицо'
    )
    print(f"Стоимость: {result2['purchase_price']} {result2['currency']}")
    print(f"Возраст: {result2['vehicle_age']} лет")
    print(f"Объем двигателя: {result2['engine_volume']}L")
    print(f"Лошадиных сил: {result2['horsepower']} HP")
    print(f"Тип импортера: {result2['importer_type']}")
    print(f"Таможенная пошлина: {result2['customs_duty']:,} RUB")
    print(f"Утилизационный сбор: {result2['recycling_fee']:,} RUB")
    print(f"Всего к оплате: {result2['total_payable']:,} RUB")
    
    # Test case 3: Car 3-5 years old with high horsepower (>160)
    print("\nТест 3: Автомобиль возрастом 4 года, более 160 л.с.")
    result3 = calculator.calculate_customs(
        purchase_price=25000,
        currency='USD',
        manufacture_date='2021-01-01',
        engine_volume=3.0,
        hp=250,
        importer_type='Физическое лицо'
    )
    print(f"Стоимость: {result3['purchase_price']} {result3['currency']}")
    print(f"Возраст: {result3['vehicle_age']} лет")
    print(f"Объем двигателя: {result3['engine_volume']}L")
    print(f"Лошадиных сил: {result3['horsepower']} HP")
    print(f"Тип импортера: {result3['importer_type']}")
    print(f"Таможенная пошлина: {result3['customs_duty']:,} RUB")
    print(f"Утилизационный сбор: {result3['recycling_fee']:,} RUB")
    print(f"Всего к оплате: {result3['total_payable']:,} RUB")

if __name__ == "__main__":
    test_calculator()