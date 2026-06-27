import requests
from bs4 import BeautifulSoup
import json
import time
import re

def get_subject_links(base_url):
    """获取所有科目页面的链接"""
    print(f"正在获取科目列表: {base_url}")
    response = requests.get(base_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    subject_links = []
    # 查找所有科目链接
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/course-descriptions/subject/' in href:
            # 检查href是否已经是完整URL
            if href.startswith('http'):
                full_url = href
            else:
                full_url = f"https://vancouver.calendar.ubc.ca{href}"
            subject_links.append(full_url)
    
    # 去重
    subject_links = list(set(subject_links))
    print(f"找到 {len(subject_links)} 个科目页面")
    return subject_links

def extract_course_info(course_element):
    """从课程元素中提取信息"""
    try:
        # 提取课程标题和代码
        title_elem = course_element.find('h3')
        if not title_elem:
            return None
            
        title_text = title_elem.get_text(strip=True)
        
        # 解析标题: "CPSC_V 100 (3) Computational Thinking"
        # 匹配格式: SUBJECT_CODE (3) Course Name
        pattern = r'([A-Z]+_[A-Z]?\d*)\s+(\d+)\s+\((\d+)\)\s+(.+?)(?:\s*\[.*\])?$'
        match = re.match(pattern, title_text)
        
        if not match:
            # 尝试另一种格式
            pattern2 = r'([A-Z]+_[A-Z]?\d*)\s+(\d+)\s+\((\d+)\)\s+(.+)$'
            match = re.match(pattern2, title_text)
            
        if match:
            code_raw = match.group(1)  # CPSC_V
            course_number = match.group(2)  # 100
            credit = float(match.group(3))  # 3
            name = match.group(4).strip()  # Computational Thinking
            
            # 格式化代码: CPSC 100
            code_parts = code_raw.split('_')
            if len(code_parts) == 2:
                code = f"{code_parts[0]} {course_number}"
            else:
                code = f"{code_raw} {course_number}"
        else:
            # 如果正则匹配失败，尝试简单解析
            parts = title_text.split('(')
            if len(parts) >= 2:
                code_part = parts[0].strip()
                credit_part = parts[1].split(')')[0].strip()
                name_part = parts[1].split(')')[1].strip() if len(parts[1].split(')')) > 1 else ''
                
                code_parts = code_part.split('_')
                if len(code_parts) == 2:
                    # 提取数字部分
                    number_match = re.search(r'\d+', code_parts[1])
                    if number_match:
                        code = f"{code_parts[0]} {number_match.group()}"
                    else:
                        code = code_part
                else:
                    code = code_part
                credit = float(credit_part) if credit_part.replace('.', '').isdigit() else 0.0
                name = name_part
            else:
                return None
        
        # 提取描述 - 找到h3后面的p标签
        desc_elem = None
        # 方法1: 找下一个兄弟元素p
        next_elem = title_elem.find_next_sibling()
        if next_elem and next_elem.name == 'p':
            desc_elem = next_elem
        else:
            # 方法2: 在父元素中找p
            parent = title_elem.find_parent()
            if parent:
                desc_elem = parent.find('p')
        
        description = desc_elem.get_text(strip=True) if desc_elem else ""
        
        # 去除"[3-1-0]"等格式信息
        description = re.sub(r'\[\d+-\d+-\d+\]\s*$', '', description).strip()
        # 去除开头的". " 
        description = re.sub(r'^\.\s+', '', description)
        # 去除多余的空格
        description = re.sub(r'\s+', ' ', description)
        
        return {
            "code": code,
            "credit": credit,
            "name": name,
            "description": description
        }
    except Exception as e:
        print(f"提取课程信息时出错: {e}")
        return None

def scrape_subject_page(url):
    """爬取单个科目页面的课程信息"""
    print(f"正在爬取: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        courses = []
        
        # 尝试多种方法查找课程块
        # 方法1: 查找所有包含h3的div
        course_blocks = []
        
        # 查找所有h3标签
        for h3 in soup.find_all('h3'):
            # 检查h3是否包含课程代码格式
            text = h3.get_text()
            if re.search(r'[A-Z]+_\w*\s+\d+\s+\(\d+\)', text):
                # 找到h3的父级div
                parent = h3.find_parent('div')
                if parent and parent not in course_blocks:
                    course_blocks.append(parent)
                else:
                    # 如果父级是p或者没有合适的父级，直接使用h3本身
                    course_blocks.append(h3)
        
        # 如果没有找到，尝试使用更通用的选择器
        if not course_blocks:
            for div in soup.find_all(['div', 'li']):
                if div.find('h3') and div.find('p'):
                    course_blocks.append(div)
        
        print(f"  找到 {len(course_blocks)} 个课程块")
        
        for block in course_blocks:
            # 如果block是h3，找它后面的p
            if block.name == 'h3':
                course_info = extract_course_info(block)
            else:
                course_info = extract_course_info(block)
            if course_info:
                courses.append(course_info)
        
        return courses
        
    except Exception as e:
        print(f"爬取 {url} 时出错: {e}")
        return []

def main():
    base_url = "https://vancouver.calendar.ubc.ca/course-descriptions/courses-subject"
    
    # 获取所有科目链接
    subject_links = get_subject_links(base_url)
    
    if not subject_links:
        print("没有找到科目链接")
        return
    
    # 只爬取前5个作为测试（可以删除这行来爬取全部）
    # subject_links = subject_links[:5]
    
    all_courses = {}
    
    # 爬取每个科目页面
    for i, link in enumerate(subject_links, 1):
        print(f"\n进度: {i}/{len(subject_links)}")
        
        # 提取科目代码作为键
        subject_code = link.split('/')[-1].upper()
        courses = scrape_subject_page(link)
        
        if courses:
            all_courses[subject_code] = courses
        
        # 礼貌性延迟
        time.sleep(1)
    
    # 保存为JSON
    output_file = 'ubc_courses.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_courses, f, ensure_ascii=False, indent=2)
    
    print(f"\n完成！共爬取 {len(all_courses)} 个科目，{sum(len(courses) for courses in all_courses.values())} 门课程")
    print(f"数据已保存到: {output_file}")

if __name__ == "__main__":
    main()